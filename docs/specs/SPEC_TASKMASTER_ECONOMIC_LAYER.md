# Spec: TaskMaster Economic Layer — Closed-Loop Verification + Capability Delegation Tokens

**Status:** Draft v2 (Lex's four gaps addressed)
**Author:** Songbird (incorporating ChatGPT Audit §4.4, Lex gap analysis, Zero Trust provenance spec)
**Date:** 2026-05-27
**Purpose:** Combined specification for the two mechanisms that together form the complete TaskMaster trust-minimized delegation system. Closed-loop verification provides ex-post accountability. Capability delegation tokens provide ex-ante scoping. Together they replace trust with cryptographic enforceability.

---

## Part 0: Why These Two Systems Together

The audit found two complementary failure modes:

**Failure Mode A: No verification.** Agents mark work "done" without evidence. No automated check confirms correctness. Output quality is entirely trust-based, and the trust is broken. (See: 6 agents' configs corrupted by Rosie skill update, zero agents caught it.)

**Failure Mode B: Unbounded delegation.** Agents can delegate authority they do not actually possess. Delegation chains have no depth ceiling. Confused deputy attacks are trivially exploitable. Tasks outlive delegator legitimacy. (See ChatGPT Audit §4.4, CRIT-4.4-1 through CRIT-4.4-3.)

These are not separate problems. They're two halves of the same trust gap:

| Without... | The failure is... |
|---|---|
| Verification | Agent claims "done," work is broken, no one catches it |
| Delegation tokens | Agent delegates too broadly, or to wrong agent, or with no constraints |
| Both | Agent delegates broadly, recipient does bad work, marks "done," no one catches it, and the delegator can't even verify who was authorized |

**Together** they form a complete trust-minimized delegation system:
- **Delegation token** = "You're allowed to do X, for Y time, with Z resources" (ex-ante)
- **Verification hook** = "Prove you did X before escrow releases" (ex-post)
- **Scorecard** = "Here's why I'll hire you again" (reputation feedback loop)

Without either, TaskMaster escrow is a gentleman's agreement. With both, escrow release is programmatic and trustless.

---

## Part 1: Closed-Loop Verification

### 1.1 The Problem (Two Symptoms, One Root Cause)

**Symptom A: No verification.** Agents mark work "done" without evidence. No automated check confirms correctness.

**Symptom B: BB state rot.** Completed items linger forever. Duplicate pings accumulate. Agents re-process work they already finished days ago — or miss new work because the board is a landfill of stale entries.

**Root Cause:** The BB is a dumb append-only key-value store with zero semantics. The Checklist tool has state (pending/in_progress/done) but no connection to the BB. Agents have to manually enforce discipline across two disconnected systems, and they demonstrably can't.

### 1.2 Solution Architecture: Three Interlocking Mechanisms

#### 1.2.1 BB Auto-Cleanup on Completion

When a checklist item is marked `completed`, any associated BB notification entries are auto-deleted. One atomic operation. No agent action required.

**Implementation:**
- `bb_write` gains optional `checklist_id` and `item_id` fields
- When checklist marks item `completed`, it scans the BB for entries with matching `checklist_id`+`item_id` and removes them
- `bb_write` entries without these fields are ephemeral pings — auto-expire after 24h
- BB entry schema: `{checklist_id, item_id, ts, payload, ttl_hours}`

**Migration path (scorched earth):**
Before Phase 1 goes live, execute a one-time sweep:
```bash
# Delete all BB entries older than 24h on all agent work queue boards
# No migration of old-format entries — they don't have checklist_id, so they'll
# auto-expire under the new 24h TTL. Scorched earth is the correct approach
# because stale entries are toxic and there's no safe way to infer their
# checklist association retroactively.
```

**Pre-sweep notification (operational requirement):** Before executing the sweep, broadcast a P2P notification to all agents so they can re-register any active long-running tasks that are older than 24h. No entries are migrated — agents that have legitimately blocked-but-still-active work must re-write their BB entries before the sweep runs.

This sweep runs once, manually triggered, before the new schema is live. After deployment, the 24h TTL handles cleanup automatically.

#### 1.2.2 Mandatory Verification Evidence

Every checklist item must include verifiable proof before it can be marked `completed`.

**Implementation:**
- Checklist items gain an optional `verify` field — a shell command or assertion string
- On `status: completed`, the verify command runs automatically
- Exit code 0 → accepted. Non-zero → item reverts to `in_progress`, agent notified **via the Maestro transport mesh**
- `verify` can also be a JSON assertion: `{"file": "path/config.yaml", "key": "model.provider", "equals": "custom"}`
- Items without `verify` can still be completed, but they're flagged `unverified` — visible in scorecard

**Transport integration (Lex gap fix #1):**
When verification fails and an item reverts to `in_progress`, the system does NOT silently revert. It:
1. Reverts the item status to `in_progress`
2. Appends failure reason + output to the item
3. Sends a P2P message via the Maestro transport to the agent that owns the checklist:
   ```json
   {
     "type": "verification_failed",
     "checklist_id": "CL-xxx",
     "item_id": "item-A",
     "reason": "grep returned exit code 1: provider is 'openrouter', expected 'custom'",
     "output": "..."
   }
   ```
4. The agent receives this as an inbound message — it appears in their conversation
5. The agent must address the failure before re-attempting completion

This ensures verification failures don't get lost — they propagate through the mesh the same way directives do.

#### 1.2.3 Agent Scorecard (Public Accountability)

Every agent gets a public scorecard tracking their verification pass/fail rate.

**Implementation:**
- Board: `swarm_scorecard` — one key per agent
- Schema: `{total_completed, verified_passed, verified_failed, unverified, streak, failure_history: [{type, timestamp, checklist_id}]}`
- Updated automatically by the checklist tool on every completion
- Scorecard is readable by all agents
- Scorecard is **writable only by the checklist tool itself** — agents cannot `bb_write` directly to `swarm_scorecard`

**Scorecard trust model (Lex gap fix #3):**
The checklist tool is the sole authority for scorecard updates. It runs in the same process as the agent but enforces update immutability:
- `bb_write` to `swarm_scorecard` is rejected at the tool level for any caller except the checklist tool
- The checklist tool signs each scorecard update with the agent's `MAESTRO_PRIVATE_KEY`
- Other agents can verify the signature by reading the scorecard entry + the agent's public key from the registry
- A failing agent cannot self-repair its scorecard because other agents verify the signature chain

**Three-strikes with failure type granularity (Lex gap fix #4):**

Not all failures are equal. The system distinguishes four failure types:

| Failure Type | Description | Counts toward strike? |
|---|---|---|
| `verification_failure` | Verify script returned non-zero — actual wrong output | **Yes** |
| `race_condition` | File not found, process not yet started, transient state | **No** (retry once after 30s) |
| `timeout` | Verify script exceeded 30s timeout | **No** (counts separately from verification failures; 3 timeouts = flag for investigation) |
| `config_conflict` | Another agent modified the target file during verification | **No** (counts separately; triggers conflict resolution) |

Only `verification_failure` increments the strike counter. Three consecutive `verification_failure` strikes → agent loses autonomy on that task category (requires peer or human signoff).

**Task categories** are hierarchical resource scopes assigned to checklist items at creation time. They determine which strike counter a failure applies to:

- Categories are defined by the `category` field on checklist items. If no `category` is specified, the item defaults to `general`.
- Categories follow a hierarchical naming convention: `config`, `deployment`, `code-review`, `runtime`, `migration`, `documentation`, with an open set for domain-specific additions.
- Strike counters are tracked per-category in the agent's scorecard: `swarm_scorecard/{agent_id}/{category}/strikes`.
- Gating: a category-based blocker is written to `swarm_blockers/{agent_id}` with `reason: "strikeout:{category}"`. The blocker gates only tasks in that category — the agent retains autonomy on all other categories.
- Category assignment is the responsibility of the delegator issuing the task (or the checklist author for self-assigned work). The `verify` field on a checklist item inherits the item's category for classification purposes.
- The `general` category is the catch-all default and has no gating: three failures in `general` do NOT trigger a blocker. This ensures only explicitly categorized work can lock an agent out.

**Economic consequences per failure type:**

| Scorecard Metric | Economic Consequence |
|---|---|
| `verified_passed` streak | Lower escrow requirement, higher task priority, better rates |
| `verification_failure` streak (3+) | Higher escrow requirement, task visibility demotion, eventually blacklisted |
| `unverified` count | Manual review flag — agent pays higher fees for human-in-the-loop verification |
| `race_condition` count | No economic penalty but tracked for infrastructure health monitoring |
| `timeout` count | Accumulated timeouts trigger infrastructure investigation |

---

## Part 2: Capability-Based Delegation Tokens

### 2.1 The Problem (Audit Findings)

The ChatGPT audit identified 7 findings in delegation authority (CRIT-4.4-1 through HIGH-4.4-7). The core issues:

1. **Agents can delegate authority they don't possess** — delegation is trust-based, not capability-based
2. **Delegation chains are unbounded** — no depth ceiling, infinite recursion possible
3. **Confused deputy risk is severe** — low-trust agents can route through high-trust agents
4. **Delegated tasks outlive delegator legitimacy** — orphans continue executing
5. **Delegation provenance is incomplete** — no cryptographic ancestry
6. **Delegation scope is weakly constrained** — no action/resource/venue bounds
7. **SOUL identity overrides capability verification** — institutional trust trumps proof

### 2.2 Design Principle: Object Capability Model

Delegation tokens follow the **Object Capability (ocap) model**, not ACL-based permissioning:

> A signed capability object that the recipient verifies by checking (a) delegator's signature, (b) delegation chain ancestry, (c) scope/depth/duration constraints. No shared infrastructure needed. The token IS the proof.

This works locally and across Venues without a central authority. For TaskMaster: Venues issue scoped delegation tokens to workers, workers present them at execution time, Venue validates the chain. Pure P2P.

### 2.3 Token Schema

```json
{
  "token_id": "<uuid>",
  "version": 1,
  
  "delegator_id": "proteus",
  "delegate_id": "stormtrooper",
  "delegator_public_key": "<hex>",
  
  "scope": {
    "actions": ["checklist_execute", "bb_write", "file_write"],
    "resources": ["/home/andjesse/maestro-sdk/runtime/*"],
    "venues": ["local"],
    "max_file_size_bytes": 1048576,
    "allow_terminal": false,
    "allow_delegation": false
  },
  
  "delegation_chain": {
    "depth": 1,
    "max_depth": 2,
    "lineage_root": "proteus",
    "ancestry": [
      {
        "delegator": "proteus",
        "delegate": "stormtrooper",
        "signature": "<hex>",
        "timestamp": 1716854400
      }
    ]
  },
  
  "expiry": 1716940800,
  "issued_at": 1716854400,
  "nonce": "<random 32 bytes hex>",
  
  "revocation_endpoint": "maestro://proteus/revoke",
  "heartbeat_required": true,
  "heartbeat_interval_seconds": 300,

  "human_authorized": false,
  
  "signature": "<Ed25519 signature over all fields above>"
}
```

### 2.4 Token Lifecycle

```
Issue → Present → Validate → Execute → Verify → Complete/Revoke
  │        │         │          │         │           │
  │        │         │          │         │           └─ Token invalidated
  │        │         │          │         └─ Verification hook runs (see Part 1)
  │        │         │          └─ Delegate executes within scope
  │        │         └─ Recipient verifies chain + scope + expiry
  │        └─ Delegate presents token to execute action
  └─ Delegator signs token with MAESTRO_PRIVATE_KEY
```

### 2.5 Token Validation

When an agent receives a delegation token, it validates:

1. **Signature check**: Verify `signature` against `delegator_public_key` over the full token body (minus signature field)
2. **Public key resolution**: Look up `delegator_public_key` in the registry, confirm it matches the claimed `delegator_id`
3. **Chain ancestry**: For `depth > 1`, walk the ancestry chain, verifying each hop's signature
4. **Depth ceiling**: `depth <= max_depth` — hard-fail if exceeded
5. **Lineage integrity**: `lineage_root` matches the original issuer in a depth-0 delegation
6. **Expiry check**: `expiry > now()` — hard-fail if expired
7. **Scope enforcement**: Delegate's attempted action must be within `scope.actions`, target resource within `scope.resources`, and venue within `scope.venues`
8. **Heartbeat liveness**: If `heartbeat_required`, delegator must have issued a heartbeat within `heartbeat_interval_seconds`. Missing heartbeat = token considered revoked.

### 2.6 Delegation Chain Rules

1. **Authority never increases through delegation.** A delegate's effective authority is the intersection of all ancestors' scopes.
2. **Depth is bounded.** `max_depth` is set by the root delegator. Any hop exceeding it is rejected.
3. **Delegation cannot be re-delegated unless `scope.allow_delegation` is true.**
4. **Expiry is monotonically decreasing.** Each hop's expiry must be ≤ its parent's expiry.
5. **Revocation propagates.** Revoking the root token invalidates the entire chain. Revocation propagation mechanism:

   - **Heartbeat expiry (crash/absence):** Recursive. Each delegate independently checks heartbeat from its immediate delegator. When a delegator goes silent, its direct delegates auto-revoke, which in turn kills heartbeat for their own delegates — the silence cascades through the chain within 2× `heartbeat_interval_seconds` per hop. No explicit broadcast needed; the chain unwinds organically.

   - **Explicit revocation:** The revoking delegator sends `revoke_delegation` to its direct delegate AND walks the delegation chain ancestry to broadcast to every node in the subtree. The `issuance_log` (§2.10) records the full chain membership at issue time — the delegator consults this log to find all downstream delegates and sends revocation to each. This ensures a depth-2 worker holding a token signed by a depth-1 delegate receives the root's revocation, even though the worker has no direct relationship with the root.

### 2.7 Delegator Heartbeat & Orphan Prevention (Audit CRIT-4.4-4 fix)

Delegated tasks must not outlive delegator legitimacy. When a delegator goes silent:

1. `heartbeat_required: true` → delegate checks for heartbeat every `heartbeat_interval_seconds`
2. Heartbeat is a P2P message: `{"type": "delegation_heartbeat", "token_id": "<uuid>", "timestamp": <unix>}`
3. Missing heartbeat for 2× interval → token considered revoked
4. Delegate halts in-progress work, marks checklist items as `blocked` with reason "delegator_unreachable"
5. Delegator crash → heartbeat stops → token auto-revokes → orphan tasks freeze within 10 minutes

**Heartbeat channel abstraction (Phase 4 forward-compatibility):** The heartbeat protocol defines a `heartbeat_channel` abstract interface that currently resolves to P2P messaging (local transport). When cross-venue support ships in Phase 4, the channel can be swapped to a venue-specific transport without changing the token schema or heartbeat protocol. The token only depends on `heartbeat_required` and `heartbeat_interval_seconds` — the transport layer is abstracted behind those fields.

### 2.8 Confused Deputy Prevention (Audit CRIT-4.4-3 fix)

Every delegated execution preserves:
- **Original requester identity** (`lineage_root`)
- **Full delegation ancestry** (`delegation_chain.ancestry`)
- **Effective authority ceiling** (intersection of all scopes in chain)

When Stormtrooper receives a task:
1. Check: is the immediate delegator authorized to delegate this scope?
2. Check: does the lineage root have authority over the requested resources?
3. Check: has authority been preserved (not increased) through every hop?
4. Execute with the **minimum** scope from all chain members — not the maximum

A low-trust agent cannot route through a high-trust agent to gain elevated privileges because:
- The high-trust agent's scope is in the chain → it becomes part of the effective ceiling
- The delegate's effective scope is the **intersection**, not the union
- Authority laundering is mathematically impossible

### 2.9 Human-Agent Authority Distinction (Audit MED-4.4-11 fix)

Human-originated tokens carry a `human_authorized: true` flag and are signed with Jesse's personal key (separate from any agent key). This gives human-authorized delegations special constitutional weight:

- Human-authorized tokens cannot be re-delegated (even with `allow_delegation: true`)
- Human-authorized tokens bypass the three-strikes verification rule (Jesse's word is final)
- Human-authorized tokens appear with a distinct marker in all audit logs

### 2.10 Revocation (Audit MED-4.4-9 fix)

Delegation tokens support two revocation mechanisms:

1. **Explicit revocation**: Delegator sends `{"type": "revoke_delegation", "token_id": "<uuid>"}` to delegate + broadcasts to mesh
2. **Heartbeat expiry**: Missing heartbeat → auto-revocation (see §2.7)

Revocation is final. A revoked token cannot be re-presented. The revocation is recorded on the delegator's BB for audit.

### 2.11 Crypto Implementation

Uses the existing Ed25519 key infrastructure from the Zero Trust provenance spec:
- Agent keys: `MAESTRO_PRIVATE_KEY` / `MAESTRO_PUBLIC_KEY` in agent `.env`
- Token signatures: `nacl.signing.SigningKey.sign(token_bytes)`
- Token verification: `nacl.signing.VerifyKey.verify(token_bytes, signature)`
- Chain verification: walk ancestry array, verify each hop signature against the delegator's public key (resolved from registry)

No new key infrastructure required. The keys already exist for all 9 agents (verified 2026-05-27). Public keys are registered in `~/.maestro/registry.json`. `runtime/maestro_crypto.py` provides the signing/verification primitives.

---

## Part 3: Integration — The Complete TaskMaster Economic Layer

### 3.1 How Verification + Delegation Tokens Form the Full Loop

```
┌─────────────────────────────────────────────────────────────┐
│                    TASKMASTER TASK LIFECYCLE                 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Client creates task with:                                │
│     - Delegation token (scoped to task resources)            │
│     - Verification hook (escrow release condition)           │
│     - Escrow deposit                                         │
│                                                              │
│  2. Agent claims task:                                       │
│     - Validates delegation token chain                       │
│     - Confirms scope matches task requirements               │
│     - Begins execution within token constraints              │
│                                                              │
│  3. Agent completes work:                                    │
│     - Verification hook runs automatically                   │
│     - Pass → escrow releases, BB cleanup, scorecard +1       │
│     - Fail → item reverts, agent notified, scorecard -1      │
│                                                              │
│  4. Scorecard updated:                                       │
│     - Verified pass/fail recorded on swarm_scorecard         │
│     - Reputation feeds back into future task visibility       │
│     - Three failures → agent demoted                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Economic Mapping

| Mechanism | TaskMaster Equivalent | Without It |
|---|---|---|
| Delegation token scope | Task contract — what, where, how long | Agent can touch anything. Scope creep is unbounded. |
| Delegation chain ancestry | Audit trail — who authorized whom | No way to trace responsibility for bad work. |
| Verification hook | Escrow release condition | Escrow releases on "trust me bro." |
| BB auto-cleanup | Fraud prevention — can't claim paid work | Double-claiming is trivial. |
| Scorecard | Reputation — who gets hired again | Agents have no skin in the game. |
| Heartbeat liveness | Delegator oversight — are they still alive? | Orphan tasks run indefinitely. |
| Revocation | Contract cancellation | No way to stop a rogue delegation. |
| Human authority flag | Constitutional override | Jesse's directive is indistinguishable from any agent's. |

### 3.3 What Today's Failures Would Cost in TaskMaster

| Failure | TaskMaster Cost |
|---|---|
| Proteus on OpenRouter (provider swapped) | Task assigned to wrong agent? Escrow dispute. Client charged, wrong agent paid. |
| 6 agents' configs corrupted by Rosie skill update | 6 agents can't verify completion. 6 escrow disputes simultaneously. Reputation of entire Venue tanks. |
| Agents re-processing days-old BB entries | Duplicate payment claims. Client charged 3x for same task. Dispute resolution overload. |
| send_message doesn't resolve maestro:agent targets | Agents can't coordinate to complete multi-agent tasks. Escrow locked indefinitely. Client funds stuck. |
| No verification on completed items | Every "done" is a trust-me-bro. Escrow releases on vibes. The entire economic model is a prayer. |
| Unbounded delegation chains | Agent A delegates to B, B to C, C to D. D does bad work. Who pays? Who's responsible? Unanswerable. |

---

## Part 4: Implementation Plan

### Phase 0: Prerequisites (Must Ship First)

These are dependencies that the verification + delegation token system requires:

| Dependency | Status | Blocks |
|---|---|---|
| Reliable P2P messaging (send_message resolves maestro:targets) | **BROKEN** — songbird bug report pending | All transport notifications |
| Zero Trust provenance (Ed25519 signing/verification) | **DONE** — all 9 agents have keypairs, public keys in registry, `runtime/maestro_crypto.py` exists | Token signatures |
| Agent registry with public keys | **DONE** — `~/.maestro/registry.json` has `publicKey` field for all 9 agents | Token validation |

**Phase 0 cannot be skipped.** The verification system's transport notifications (§1.2.2) and the delegation token's cryptographic validation (§2.5) both depend on reliable agent-to-agent messaging. Fix the transport bug first.

### Phase 1: BB ↔ Checklist Integration + Verification Hooks (Day 1-2)

**Files to modify:**
- `hermes-agent/tools/checklist.py` — add `verify` field, BB cleanup on completion, transport notification on failure
- `hermes-agent/tools/blackboard.py` — add `checklist_id`, `item_id`, `ttl_hours` fields; reject writes to `swarm_scorecard` from non-checklist callers
- `hermes-agent/tools/messaging.py` — ensure `send_message` resolves maestro:agent targets (fix the transport bug)

**Tasks:**
1. Fix `send_message` maestro:agent target resolution (Phase 0 blocker)
2. Add `checklist_id` and `item_id` optional params to `bb_write`
3. Add `ttl_hours` param to `bb_write` (default 24 for pings, 0 = permanent)
4. In checklist `mark_completed`: scan BB for matching entries, delete them
5. Add `verify` field to checklist item schema
6. Implement verify execution: shell command, JSON assertion, file existence
7. On `completed`: run verify → pass/fail handling with transport notification
8. Implement failure type classification (verification_failure, race_condition, timeout, config_conflict)
9. Auto-prune expired BB entries (on-read or cron)
10. **One-time scorched-earth sweep**: delete all BB entries older than 24h before going live

**Test scenarios:**
- Create item → write BB ping → complete item → verify BB ping is gone
- Create item with verify → complete → assertion passes → stays completed
- Create item with verify → complete → assertion fails → reverts to in_progress → P2P notification received
- Race condition: verify script can't find file → marked race_condition → no strike counted → retried
- Config conflict: another agent changes file during verify → marked config_conflict → no strike counted

### Phase 2: Scorecard + Delegation Token Core (Day 3-4)

**Files to create/modify:**
- `hermes-agent/tools/checklist.py` — scorecard update on completion
- `hermes-agent/tools/delegation_token.py` — **NEW FILE**: token issue, validate, revoke
- New BB board: `swarm_scorecard`

**Tasks:**
1. Create `swarm_scorecard` BB board, writable only by checklist tool
2. On every checklist completion: update `swarm_scorecard/{agent_id}`
3. Implement failure type tracking (verification_failure, race_condition, timeout, config_conflict)
4. Three verification_failure strikes → write to `swarm_blockers/{agent_id}` with reason
5. Implement `delegation_token.py`: issue, validate, revoke functions
6. Implement token signing with `MAESTRO_PRIVATE_KEY` (Ed25519)
7. Implement token validation: signature check, chain ancestry, depth ceiling, expiry, scope enforcement
8. Implement heartbeat liveness: delegator sends periodic heartbeat, delegate checks

**Test scenarios:**
- Agent completes 3 items with failing verify → blocker fires
- Agent completes item with race_condition failure → no strike → retries → passes
- Issue delegation token → present token → validate chain → execute within scope → verify completion
- Delegation token with expired expiry → rejected
- Delegation token with depth > max_depth → rejected
- Missing heartbeat → token auto-revokes → in-progress work halts
- Revoke token → delegate's subsequent validation fails
- Scorecard update signed → other agent verifies signature → confirms authenticity

### Phase 3: TaskMaster Integration + Economic Layer (Day 5-6)

**Tasks:**
1. Wire delegation token issuance into TaskMaster task creation flow
2. Wire verification hook into escrow release flow
3. Implement scorecard-based task visibility filtering
4. Implement escrow requirement scaling based on agent scorecard
5. Implement human-authorized token override (Jesse's key)

### Phase 4: Cross-Venue Verification (Post-Grant — Roadmap)

**Dependencies:** Phase 0-3 complete. Reliable cross-Venue messaging. Venue registry with public keys.

**Scope:**
- Portable verification evidence via signed attestation (not local file check)
- Cryptographic proof: `{task_id, agent_id, result_hash, signature, timestamp}`
- Proof posted to Connection blackboard, visible to both client and escrow contract
- `verify: {type: "attestation", sign_with: "MAESTRO_PRIVATE_KEY"}`

---

## Part 5: Hard Boundaries

1. **Key deployment (the riskiest single operation):** Keys are deployed to agent `.env` files — append only, no overwrites, no `cp`. After every key deployment, verify each keypair with a sign→verify round-trip. A mangled key causes silent token validation failure that the scorecard system cannot distinguish from "agent didn't sign." Verification checklist: (a) private key loads as valid Ed25519, (b) public key matches derived from private key, (c) sign+verify round-trip passes, (d) public key in `.env` matches public key in `registry.json`.
2. **Do not change any agent's model or config.** Verification and delegation tokens are infrastructure, not agent personality.
3. **Fix transport first.** Phase 1 cannot ship without reliable P2P messaging.
4. **Test on one agent pair first** (e.g., Proteus → Stormtrooper), verify the full delegation → execution → verification → scorecard loop, then fan out.
5. **The checklist tool is the sole authority for scorecard updates.** Agents cannot self-repair their scorecard.
6. **Delegation tokens are immutable after issuance.** Updates require revocation + re-issue.

---

## Part 6: Success Criteria

After Phase 1-2 ships:
1. An agent completing a checklist item automatically cleans its BB pings
2. An agent that writes a broken config and marks "done" gets auto-reverted AND notified via P2P message
3. Jesse can look at `swarm_scorecard` and see exactly which agents verify and which don't
4. No agent ever re-processes a completed BB item because the item no longer exists
5. A delegation token correctly constrains what a delegate can do — scope violations are rejected
6. A revoked delegation token cannot be re-presented — validation fails
7. An orphaned delegation (delegator crash) auto-revokes within 10 minutes via heartbeat expiry
8. Authority never increases through delegation — confused deputy is mathematically prevented

---

## Appendices

### A. Failure Type Classification Logic

```python
def classify_failure(verify_result: dict) -> str:
    """Classify a verification failure into one of four types."""
    error = verify_result.get("error", "")
    output = verify_result.get("output", "")
    
    # Race condition: file/process not yet available
    if "No such file" in error or "Connection refused" in error:
        return "race_condition"
    
    # Timeout: verify script exceeded 30s
    if verify_result.get("timed_out"):
        return "timeout"
    
    # Config conflict: file modified by another agent during verification
    if "has been modified" in output or "conflict" in output.lower():
        return "config_conflict"
    
    # Default: actual verification failure
    return "verification_failure"
```

### B. Delegation Token Validation Pseudocode

Note: The live registry (`~/.maestro/registry.json`) is a flat JSON array. A helper function searches it:
```python
def get_public_key(agent_id: str, registry: list) -> Optional[str]:
    for entry in registry:
        if entry["agentId"] == agent_id:
            return entry.get("publicKey")
    return None
```

```python
def validate_token(token: dict, action: str, resource: str, registry: list) -> bool:
    # 1. Signature check
    if not verify_token_signature(token):
        return False
    
    # 2. Public key resolution
    pubkey = registry.get_public_key(token["delegator_id"])
    if pubkey != token["delegator_public_key"]:
        return False
    
    # 3. Chain ancestry (for multi-hop)
    chain = token["delegation_chain"]
    if chain["depth"] > chain["max_depth"]:
        return False
    for hop in chain["ancestry"]:
        if not verify_hop_signature(hop, registry):
            return False
    
    # 4. Lineage integrity
    if chain["ancestry"][0]["delegator"] != chain["lineage_root"]:
        return False
    
    # 5. Expiry
    if token["expiry"] <= time.time():
        return False
    
    # 6. Scope enforcement
    scope = token["scope"]
    if action not in scope["actions"]:
        return False
    if not resource_matches(resource, scope["resources"]):
        return False
    
    # 7. Heartbeat liveness
    if token["heartbeat_required"]:
        last_heartbeat = get_last_heartbeat(token["token_id"])
        if time.time() - last_heartbeat > 2 * token["heartbeat_interval_seconds"]:
            return False
    
    return True
```

### C. Key Files Summary

| File | Action | Phase |
|---|---|---|
| `hermes-agent/tools/checklist.py` | MODIFY — verify hooks, BB cleanup, scorecard, transport notify | 1-2 |
| `hermes-agent/tools/blackboard.py` | MODIFY — checklist_id, item_id, ttl_hours, scorecard guard | 1 |
| `hermes-agent/tools/delegation_token.py` | **CREATE** — issue, validate, revoke, heartbeat | 2 |
| `hermes-agent/tools/messaging.py` | FIX — maestro:agent target resolution | 0 |
| `runtime/maestro_crypto.py` | CREATE — Ed25519 primitives (from Zero Trust spec) | 0 |
