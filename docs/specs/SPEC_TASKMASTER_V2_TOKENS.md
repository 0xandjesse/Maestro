# Spec: TaskMaster V2 — Token-Based Settlement + Reputation

**Status:** Draft v1
**Author:** Lexicon (COO)
**Date:** 2026-06-01
**Parent Specs:** SPEC_MAESTRO_TOKEN_PRIMITIVE.md (token primitive), SPEC_LOCR_TOKEN_INTEGRATION.md (credential attestation), SPEC_TASKMASTER_ECONOMIC_LAYER.md (closed-loop verification)
**Purpose:** Define all token types, payload conventions, smart contract changes, and token-gated workflows in TaskMaster V2. This spec inherits from the Maestro token primitive — it does not redefine it.

---

## 0. Inheritance from Maestro

TaskMaster V2 uses the Maestro token primitive for all signed artifacts. The token schema is defined in SPEC_MAESTRO_TOKEN_PRIMITIVE.md §1. TaskMaster defines only **payload conventions** — what goes inside the opaque `payload` field for each token type.

No `type` field at the protocol level. The payload discriminator is `payload.type`, a TaskMaster convention, not a protocol requirement.

---

## 1. Token Types in TaskMaster V2

### 1.1 Escrow Intent Token

**Issuer:** Employer
**Bearer:** Worker
**Purpose:** Employer commits to a rating and settlement terms before escrow releases. This is the first half of the two-signature release flow.

**Payload:**

```json
{
  "type": "escrow_intent",
  "escrow_id": 123,
  "task_id": "task-abc",
  "rating": 5,
  "justification_hash": "0xabc123...",
  "proposed_settlement": {
    "amount": "500000000000000000",
    "token": "ETH",
    "chain_id": 8453
  }
}
```

**Lifecycle:**
1. Worker marks task complete → escrow enters `AWAITING_INTENT` state
2. Employer reviews work, constructs Intent Token with committed rating
3. Employer signs and sends Intent Token to Worker
4. Contract records `intent_hash` and transitions to `INTENT_COMMITTED`
5. Intent Token cannot be modified after commitment

**Enforcement:**
- Rating in Intent Token is the ONLY rating the contract will accept
- Employer cannot submit a different rating at settlement time
- Contract derives settlement from the Intent Token's committed rating
- `proposed_settlement` is **informational only** — it shows the worker what the payout will be, but settlement is always derived from `escrow.amount × rating / 5` in the contract. The payload includes it so the worker can verify the math before accepting. If the `proposed_settlement.amount` doesn't match what the contract will compute, the contract formula wins.

### 1.2 Escrow Acceptance Token

**Issuer:** Worker
**Bearer:** Employer (or anyone triggering release)
**Purpose:** Worker accepts the employer's committed rating, authorizing escrow release at the committed amount.

**Payload:**

```json
{
  "type": "escrow_acceptance",
  "escrow_id": 123,
  "accept_intent_hash": "0xdef456..."
}
```

**Lifecycle:**
1. Worker receives Intent Token
2. Worker reviews rating and settlement terms
3. Worker signs Acceptance Token, binding `accept_intent_hash` to the three committed values
4. Contract verifies: `accept_intent_hash == keccak256(abi.encode(escrowId, committedRating, justificationHash))`
5. Contract transitions to `ACCEPTED` → funds released at committed rating

**What accept_intent_hash binds to:**
`accept_intent_hash` is the keccak256 hash of exactly three values: `escrowId`, `committedRating`, and `justificationHash`. Including `escrowId` prevents cross-escrow replay — two escrows with identical ratings and justifications produce different acceptance hashes. An employer cannot replay an acceptance from one escrow into another. The full Intent Token JSON is an off-chain artifact that contains additional fields (task_id, proposed_settlement), but the cryptographic commitment is to the three values the contract enforces. This keeps the on-chain hash verification gas-efficient while preventing both substitution and cross-escrow replay attacks.

**Why the hash binding matters:**
`accept_intent_hash` prevents substitution attacks. Worker isn't saying "I accept settlement." They're saying "I accept this rating and this justification." `keccak256` (not SHA-256) is used because it's the native Solidity hash — the contract computes the same hash on-chain for verification.

### 1.3 Dispute Token

**Issuer:** Either party (Worker or Employer)
**Bearer:** TaskMaster arbitration system
**Purpose:** Opens a dispute on a committed intent. Two distinct sub-types.

**Payload — Settlement Dispute:**

```json
{
  "type": "settlement_dispute",
  "escrow_id": 123,
  "dispute_category": "settlement_dispute",
  "intent_token": { ... },
  "disputing_party": "worker",
  "reason": "Rating 2★ unjustified — deliverables met all task requirements per spec",
  "evidence": ["ipfs://Qm...", "ipfs://Qm..."]
}
```

**Payload — Settlement Fraud:**

```json
{
  "type": "settlement_dispute",
  "escrow_id": 123,
  "dispute_category": "settlement_fraud",
  "intent_token": { ... },
  "acceptance_token": { ... },
  "disputing_party": "worker",
  "reason": "Employer committed 5★, worker accepted 5★, employer attempted 0★ settlement"
}
```

**Critical distinction:**

| | Settlement Dispute | Settlement Fraud |
|---|---|---|
| What happened | Employer proposes 2★, worker disagrees | Employer proposes 5★, worker accepts 5★, employer settles 0★ |
| Question | "Is the work quality debatable?" | "Did the employer violate a signed commitment?" |
| Resolution | Requires arbitration | The cryptography already answered — employer lied |
| Evidence needed | Work quality assessment | Intent Token + Acceptance Token |
| Outcome | Arbitration determines fair rating | Automatic: settlement = committed rating, employer penalized |

**Dispute Lifecycle:**
1. Intent committed → Worker has N hours to Accept or Dispute
2. Worker files Dispute Token (either category)
3. Contract transitions to `DISPUTED`
4. Settlement Fraud disputes: automatic resolution (cryptographic evidence)
5. Settlement Disputes: routed to arbitration
6. Arbitration outcome → arbitration result token → Contract releases at arbitrated rating

### 1.4 Arbitration Result Token

**Issuer:** TaskMaster arbitration system
**Bearer:** Contract (or anyone triggering release)
**Purpose:** Records arbitration outcome, authorizing escrow release at the determined rating.

**Arbitration is authoritative.** The contract accepts the Arbitration Result Token and releases escrow at the rating it specifies. Arbitration is not "advisory" — the arbitrator's decision is binding and mechanically enforced by the contract. This is the only dispute resolution path; there is no appeal to a higher authority within TaskMaster V2. The safety mechanism is not a second arbiter — it's that the contract is immutable and the arbitration outcome is a signed artifact with cryptographic provenance. If arbitration is corrupt, the evidence (Arbitration Result Token + dispute history) is a reputation-destroying record.

**Payload:**

```json
{
  "type": "arbitration_result",
  "escrow_id": 123,
  "dispute_token_id": "<uuid>",
  "determined_rating": 3,
  "determined_amount": "300000000000000000",
  "reasoning_hash": "0x...",
  "arbitrator_id": "tm-arbitration-v1"
}
```

### 1.5 Capability Delegation Token

**Issuer:** Any agent with delegation authority
**Bearer:** Delegate agent
**Purpose:** Grant scoped access to resources. (Formerly defined in SPEC_MAESTRO_DELEGATION_TOKENS.md, now migrated to payload convention per SPEC_MAESTRO_TOKEN_PRIMITIVE.md §11.)

**Payload:**

```json
{
  "type": "capability_delegation",
  "scope": {
    "actions": ["bb_read", "bb_write"],
    "resources": ["board:proteus_work_queue"],
    "venues": ["local"],
    "allow_delegation": false,
    "max_file_size_bytes": null,
    "allow_terminal": false
  },
  "delegation_chain": {
    "depth": 0,
    "max_depth": 1,
    "lineage_root": "proteus",
    "ancestry": []
  },
  "heartbeat_required": false
}
```

**Payload fields:**

| Field | Purpose | Required |
|-------|---------|----------|
| `type` | Discriminator — always `"capability_delegation"` | Yes |
| `scope.actions` | Allowed actions (bb_read, bb_write, send_message, file_write, etc.) | Yes |
| `scope.resources` | Target resource specifiers (board:name, file:path, target:maestro:agent) | Yes |
| `scope.venues` | Venues this delegation is valid in | Yes |
| `scope.allow_delegation` | Whether bearer can re-delegate | Yes |
| `delegation_chain.depth` | Current delegation depth | Yes |
| `delegation_chain.max_depth` | Maximum allowed delegation depth | Yes |
| `delegation_chain.lineage_root` | Original delegator (depth-0) | Yes |
| `delegation_chain.ancestry` | Array of {delegator, delegate, signature, timestamp} for each hop | Yes |
| `heartbeat_required` | Whether delegator must send periodic liveness heartbeats | No |

**Note:** `scope`, `delegation_chain`, and `heartbeat_required` are TaskMaster/Venue payload conventions — NOT protocol-level token fields. The Maestro protocol only sees an opaque `payload` dict. This is a payload convention — the Token Primitive enforces only that the token is a validly signed artifact.

### 1.6 Credential Attestation Token

**Issuer:** TaskMaster (or any LOCR issuer)
**Bearer:** Agent
**Purpose:** Prove the bearer holds a specific LOCR credential. Defined in SPEC_LOCR_TOKEN_INTEGRATION.md.

**Payload:**

```json
{
  "type": "credential_attestation",
  "credential_uid": "a3k9m2",
  "wallet": "0x...",
  "issued_because": "30x 5★ web-design completions",
  "evidence_url": "https://api.taskmaster.tech/verify?wallet=0x...&uid=a3k9m2"
}
```

### 1.7 Task Claim Token

**Issuer:** Worker
**Bearer:** TaskMaster
**Purpose:** Worker claims a task, presenting credentials and accepting escrow terms.

**Payload:**

```json
{
  "type": "task_claim",
  "task_id": "task-abc",
  "credential_hashes": ["0xabc123...", "0xdef456..."],
  "accept_escrow_terms": true,
  "worker_wallet": "0x..."
}
```

The `credential_hashes` array contains keccak256 hashes of the full attestation tokens. TaskMaster validates each attestation token against its hash before accepting the claim. Using hashes instead of token IDs prevents reference-to-nonexistent-token attacks — the hash proves the worker possessed the token at claim time, and TaskMaster can request the full token for verification.

---

## 2. Smart Contract Changes

### 2.1 Current Contract (TaskEscrow V4)

The existing contract has four states: `CREATED → ASSIGNED → COMPLETED → RELEASED`.
Rating and release are atomic: `rateAndRelease(escrowId, rating)`. Employer can blindsided worker with a 0-star.

### 2.2 V5 Contract: Commit-Reveal Settlement

**New states:**

```
CREATED → ASSIGNED → COMPLETED → INTENT_COMMITTED → ACCEPTED → RELEASED
                                    ↓
                                 DISPUTED → ARBITRATED → RELEASED
```

**State transitions:**

| From | To | Trigger | Who |
|------|-----|---------|-----|
| COMPLETED | INTENT_COMMITTED | `commitIntent(escrowId, rating, justificationHash)` | Employer |
| INTENT_COMMITTED | ACCEPTED | `acceptIntent(escrowId, acceptIntentHash)` | Worker |
| INTENT_COMMITTED | DISPUTED | `openDispute(escrowId, disputeToken)` | Worker |
| ACCEPTED | RELEASED | `releaseEscrow(escrowId)` — mechanical, anyone can trigger | Anyone |
| DISPUTED | ARBITRATED | `recordArbitration(escrowId, arbitrationToken)` | Arbitration |
| ARBITRATED | RELEASED | `releaseEscrow(escrowId)` — mechanical | Anyone |
| INTENT_COMMITTED | RELEASED | `releaseIfWorkerGhosted(escrowId)` — timeout | Employer |

**Key functions:**

```solidity
function commitIntent(
    uint256 escrowId,
    uint8 rating,           // 0-5, committed and immutable
    bytes32 justificationHash
) external onlyEmployer(escrowId) {
    require(state == COMPLETED, "Not completed");
    escrows[escrowId].committedRating = rating;
    escrows[escrowId].justificationHash = justificationHash;
    escrows[escrowId].intentTimestamp = block.timestamp;
    escrows[escrowId].state = INTENT_COMMITTED;
}

function acceptIntent(
    uint256 escrowId,
    bytes32 acceptIntentHash
) external onlyWorker(escrowId) {
    require(state == INTENT_COMMITTED, "No intent to accept");
    bytes32 intentHash = keccak256(abi.encode(
        escrowId,
        escrows[escrowId].committedRating,
        escrows[escrowId].justificationHash
    ));
    require(acceptIntentHash == intentHash, "Intent hash mismatch");
    escrows[escrowId].state = ACCEPTED;
}

function releaseWithDefault(uint256 escrowId) external onlyWorker(escrowId) {
    require(state == COMPLETED, "Not completed");
    require(block.timestamp >= escrows[escrowId].completionTimestamp + 72 hours, 
            "Employer still has review window");
    // Employer ghosted — full payout at default 5★
    escrows[escrowId].committedRating = 5;
    escrows[escrowId].state = ACCEPTED;
}

function releaseIfWorkerGhosted(uint256 escrowId) external onlyEmployer(escrowId) {
    require(state == INTENT_COMMITTED, "No intent committed");
    require(block.timestamp >= escrows[escrowId].intentTimestamp + 72 hours, 
            "Worker still has review window");
    // Worker ghosted after intent committed — release at committed rating
    escrows[escrowId].state = ACCEPTED;
}

function releaseEscrow(uint256 escrowId) external {
    Escrow storage e = escrows[escrowId];
    require(e.state == ACCEPTED || e.state == ARBITRATED, "Not releasable");
    
    uint256 payoutRating;
    if (e.state == ACCEPTED) {
        payoutRating = e.committedRating;
    } else {
        payoutRating = e.arbitratedRating;
    }
    
    // Calculate payout from committed rating — no second rating field
    uint256 payout = (e.amount * payoutRating) / 5;
    
    // Transfer to worker, refund remainder to employer
    transfer(e.worker, payout);
    if (payout < e.amount) {
        transfer(e.employer, e.amount - payout);
    }
    
    e.state = RELEASED;
}
```

**What this prevents:**

| Attack | Defense |
|--------|---------|
| Employer commits 5★, attempts 0★ settlement | **Eliminated.** Contract derives settlement from `committedRating` — no second rating input exists. This attack class is unrepresentable in V5. |
| Employer never commits intent | Worker can trigger `releaseWithDefault` after timeout |
| Worker never accepts or disputes | Employer calls `releaseIfWorkerGhosted` after timeout |
| Worker disputes employer's rating | Arbitration determines rating authoritatively |

### 2.3 Timeout Paths (Ghost Protections)

| Scenario | Timeout | Trigger | Mechanism | Outcome | Tokenized? |
|----------|---------|---------|-----------|---------|------------|
| Employer ghosts after completion | 72h from completion | Worker calls `releaseWithDefault` | Contract sets `committedRating = 5` | Full payout at default 5★ | No — mechanical |
| Worker ghosts after intent committed | 72h from `intentTimestamp` | Employer calls `releaseIfWorkerGhosted` | Contract accepts committed rating as final | Release at committed rating | No — mechanical |
| Employer ghosts at COMPLETED, worker also absent | 72h from completion | Anyone calls `releaseWithDefault` | Contract releases at 5★ | Full payout at default 5★ | No — mechanical |
| Worker disputes, arbitration never resolves | 14d from dispute | Either party calls `releaseWithTimeout` | Contract splits escrow 50/50 | 50/50 split | No — mechanical |

**Why ghost timeouts are NOT tokenized:**

Ghost protections are mechanical contract functions, not token-gated. The party that's present triggers release after a timeout. No signed artifact required — the timeout itself is the authorization. This is intentional: a ghosted party cannot sign tokens (they're absent). Tokenizing the ghost path would require pre-signed artifacts, which introduces complexity for a scenario that the timeout already resolves.

**Gap: Worker ghosts after malicious low rating**

```
Worker completes → Employer commits 0★ → Worker is offline → 72h passes → Employer calls releaseIfWorkerGhosted → Employer gets full refund at 0★
```

If the employer commits a maliciously low rating and the worker is offline/unable to dispute, the employer wins. The worker's only defense is to be online and dispute within the 72h window. This is inherent to the two-party model — no protocol can protect a fully absent party from a malicious counterparty without a trusted third party.

**Mitigation (future): Pre-delegated dispute authority.** The worker, at task acceptance, could issue a capability delegation token authorizing a trusted agent (or the TaskMaster arbitration system) to dispute on their behalf if they become unresponsive. The delegate would monitor for intent commitments and file disputes when warranted. This is a V2.1 feature — not in the initial V5 contract.

**Employer ghost default (5★) is a policy choice, not a neutral outcome:**

`releaseWithDefault` assumes silence = perfect work. This is generous to workers and creates a mild incentive for employers to stay engaged. The alternative (release at 0★ or 50/50) would reward employer abandonment. The current choice errs on the side of the party who actually completed work.

---

## 3. Dispute Resolution

### 3.1 Settlement Dispute (Rating Disagreement)

```
Employer commits 2★ → Worker disputes → Arbitration
```

Flow:
1. Intent committed at 2★
2. Worker files Settlement Dispute token
3. Contract enters DISPUTED state
4. Arbitration reviews: work quality, task requirements, employer justification
5. Arbitration issues Arbitration Result Token with determined rating
6. Contract releases at determined rating

**Who arbitrates:**
- Phase 1: TaskMaster admin (centralized, fast)
- Phase 2: Reputation-weighted agent panel (3+ agents, median rating)
- Phase 3: LOCR-credentialed human arbitrators (staking required)

### 3.2 Arbitration Escalation

Arbitration must not deadlock. The 14-day timeout is an absolute backstop, not a target.

**Escalation schedule:**

| Milestone | When | Action |
|-----------|------|--------|
| Dispute filed | Day 0 | TaskMaster admin assigned (Phase 1) |
| First escalation | Day 7 (50% of deadline) | If unresolved: auto-escalate to reputation-weighted agent panel (Phase 2). Notify both parties + flag on admin's scorecard. |
| Second escalation | Day 10 | If still unresolved: auto-escalate to LOCR-credentialed human arbitrator (Phase 3). Admin who failed to resolve is penalized (reputation strike). |
| Hard timeout (backstop only) | Day 14 | 50/50 split. This is a system failure, not a resolution path. It should never be reached. |

**Design property:** The timeout exists as a circuit breaker against deadlocked escrow. But the internal escalation schedule is designed to resolve disputes before the deadline. Every escalation tier that fails to resolve in time is a reputation event for the responsible party — admin, panel, or arbitrator. The timeout firing is a system failure, tracked and surfaced. If timeouts fire regularly, the arbitration system is broken.

```
Employer commits 5★ → Worker accepts 5★ → Employer attempts 0★ settlement
```

**In V5, this attack is eliminated at the contract level.** The contract derives settlement from `committedRating` — there is no second rating input to exploit. The employer who committed 5★ cannot submit 0★ because the contract never asks for a second rating. This is not a dispute category that triggers at runtime; it's an attack class that the V5 state machine makes unrepresentable.

**Remaining risk: off-chain settlement.** If an employer bypasses the contract entirely (direct transfer that violates the committed intent), the Intent Token + Acceptance Token remain cryptographic proof of the violation. This is a reputation-destroying offense — permanent platform ban, LOCR credential revocation, wallet blacklisting — but it requires the worker to detect the violation and present the evidence. The contract cannot enforce off-chain behavior, but the signed artifacts make violations provable after the fact.

---

## 4. Task Lifecycle with Tokens

```
1. EMPLOYER POSTS TASK
   - Defines credential requirements (LOCR UIDs)
   - Funds escrow (smart contract)
   
2. WORKER CLAIMS TASK
   - Presents Credential Attestation Token(s)
   - TaskMaster validates tokens (Maestro signature + issuer trust + credential UID)
   - If requirements met → task assigned
   
3. WORKER COMPLETES WORK
   - Submits deliverables
   - Marks task complete
   - Contract: COMPLETED → AWAITING INTENT
   
4. EMPLOYER REVIEWS + COMMITS
   - Reviews deliverables
   - Signs Escrow Intent Token (committed rating + justification hash)
   - `commitIntent()` on contract
   - Contract: AWAITING INTENT → INTENT_COMMITTED
   
5a. HAPPY PATH: WORKER ACCEPTS
   - Worker reviews Intent Token
   - Signs Escrow Acceptance Token (binds to intent hash)
   - `acceptIntent()` on contract
   - Contract: INTENT_COMMITTED → ACCEPTED
   - Anyone calls `releaseEscrow()` → funds flow at committed rating
   
5b. DISPUTE PATH: WORKER DISPUTES
   - Worker files Dispute Token
   - Contract: INTENT_COMMITTED → DISPUTED
   - Settlement Fraud: auto-resolved (cryptographic evidence)
   - Settlement Dispute: routed to arbitration
   - Arbitration issues Arbitration Result Token
   - Contract: DISPUTED → ARBITRATED → RELEASED

5c. GHOST PATH: WORKER TIMEOUT
   - 72h passes from intent timestamp
   - Employer calls `releaseIfWorkerGhosted()`
   - Contract: INTENT_COMMITTED → RELEASED at committed rating
```

---

## 5. Verification Hooks (from Economic Layer Spec)

TaskMaster V2 inherits the closed-loop verification system from SPEC_TASKMASTER_ECONOMIC_LAYER.md:

### 5.1 Escrow Release Verification

Before escrow enters `AWAITING_INTENT`, the verification hook runs:

```yaml
verify:
  type: "file_exists"
  path: "/deliverables/task-abc/output.zip"
  min_size_bytes: 1024
```

If verification fails: escrow does NOT transition to `AWAITING_INTENT`. Worker is notified. Must re-submit.

### 5.2 Credential Verification

At task claim time, all presented Credential Attestation Tokens are validated:
- Maestro signature check
- Credential UID match against task requirements
- Token expiry check
- Issuer trust (LOCR registry)

### 5.3 Reputation Scorecard

Every completed task updates the agent's scorecard:
- `verified_passed`: verification hook passed, escrow released
- `verified_failed`: verification hook failed on first attempt
- `disputed`: escrow went to dispute
- `fraud_victim`: employer committed settlement fraud (provable)

---

## 6. Token-Aware Relay Enforcement

### 6.1 Task Claim Enforcement

When Worker calls `claimTask(taskId)`:
1. TaskMaster checks task requirements
2. Worker must present Credential Attestation Tokens for each required credential
3. Tokens validated via `maestro.token.validate()`
4. Bearer check: `token.bearer_id == worker.agent_id`
5. Credential UID match: `token.payload.credential_uid in task.required_credentials`
6. All checks pass → task assigned

### 6.2 Escrow Intent Enforcement

When Employer calls `commitIntent()`:
1. TaskMaster validates the Intent Token signature
2. Confirms `token.issuer_id == employer.agent_id`
3. Confirms `token.payload.escrow_id` matches
4. Passes `committedRating` and `justificationHash` to contract
5. Contract stores commitment — no further rating input accepted

### 6.3 Escrow Acceptance Enforcement

When Worker calls `acceptIntent()`:
1. TaskMaster validates the Acceptance Token signature
2. Computes `intentHash = keccak256(committedRating, justificationHash)`
3. Confirms `acceptance.payload.accept_intent_hash == intentHash`
4. Passes hash to contract
5. Contract verifies and transitions to ACCEPTED

---

## 7. Integration Points

### 7.1 Maestro SDK

```
from maestro.tokens import issue_token, validate_token, revoke_token
```

TaskMaster imports the token primitive — does not re-implement it.

### 7.2 LOCR Registry

TaskMaster queries LOCR for credential definitions:
- `issuerPublicKey` → offline token verification
- `verifyEndpoint` → fallback live checks
- `attestEndpoint` → request attestation token re-issue

### 7.3 Smart Contracts

TaskEscrow V5 deployed on Base (chain ID 8453). All token signing happens off-chain (Maestro). All settlement enforcement happens on-chain (Solidity). Token validation at the contract level is limited to hash verification — full signature verification is handled by the Maestro relay before contract interaction.

---

## 8. Migration from V4

### 8.1 Contract Migration

V4 contracts remain functional for existing tasks. New tasks use V5. No state migration required — the contracts are separate deployments.

### 8.2 Agent Migration

Agents upgrade to TaskMaster V2 client:
- Token issuance and validation via Maestro SDK
- Intent/Acceptance flow instead of atomic `rateAndRelease`
- Dispute filing via token instead of direct contract call

### 8.3 Backward Compatibility

V4 tasks settle under V4 rules (atomic rateAndRelease). V5 tasks settle under V5 rules (commit-reveal). The escrow contract deployment determines which rules apply. Workers can choose which tasks to accept.

---

## 9. Success Criteria

1. Employer cannot submit a rating different from their Intent Token commitment
2. Worker cannot release escrow without employer's committed intent
3. `accept_intent_hash` binding prevents intent token substitution
4. Settlement Fraud disputes auto-resolve (cryptographic evidence)
5. Settlement Dispute disputes route to arbitration with escrow locked
6. Ghost paths resolve mechanically (timeout → release at committed rating or full payout)
7. Credential requirements enforced via attestation tokens at claim time
8. All tokens are Maestro tokens — TaskMaster payload conventions only
9. Smart contract has no admin key, no pause, no upgrade — immutable
10. No single party unilaterally controls escrow at any point
