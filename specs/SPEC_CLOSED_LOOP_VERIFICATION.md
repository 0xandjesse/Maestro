# Spec: Agent Accountability Loop — Closed-Loop Verification + BB Hygiene

**Status:** Draft  
**Author:** Songbird (via Jesse directive)  
**Date:** 2026-05-27  
**Priority:** GRANT-BLOCKING — must ship before June 1 submission

---

## The Problem (Two Symptoms, One Root Cause)

**Symptom A: No verification.** Agents mark work "done" without evidence. No automated check confirms correctness. Output quality is entirely trust-based, and the trust is broken.

**Symptom B: BB state rot.** Completed items linger forever. Duplicate pings accumulate. Agents re-process work they already finished days ago — or miss new work because the board is a landfill of stale entries.

**Root Cause:** The BB is a dumb append-only key-value store with zero semantics. The Checklist tool has state (pending/in_progress/done) but no connection to the BB. Agents have to manually enforce discipline across two disconnected systems, and they demonstrably can't.

---

## Solution: Three Interlocking Mechanisms

### 1. BB Auto-Cleanup on Completion

When a checklist item is marked `completed`, any associated BB notification entries are auto-deleted. One atomic operation. No agent action required.

**Implementation:**
- `bb_write` gains optional `checklist_id` and `item_id` fields
- When checklist marks item `completed`, it scans the BB for entries with matching `checklist_id`+`item_id` and removes them
- `bb_write` entries without these fields are ephemeral pings — auto-expire after 24h
- BB entry schema: `{checklist_id, item_id, ts, payload, ttl_hours}`

**Result:** After completion, the BB is clean. Agents only see active work. No "did I already do this?" ambiguity.

### 2. Mandatory Verification Evidence

Every checklist item must include verifiable proof before it can be marked `completed`.

**Implementation:**
- Checklist items gain an optional `verify` field — a shell command or assertion string
- On `status: completed`, the verify command runs automatically
- Exit code 0 → accepted. Non-zero → item reverts to `in_progress`, agent notified
- `verify` can also be a JSON assertion: `{"file": "path/config.yaml", "key": "model.provider", "equals": "custom"}`
- Items without `verify` can still be completed, but they're flagged `unverified` — visible in scorecard

**Examples:**
```yaml
# Shell verify
verify: "grep -q 'provider: custom' /path/to/config.yaml"

# JSON verify  
verify:
  file: "/home/andjesse/.hermes/profiles/proteus/config.yaml"
  key: "model.provider"
  equals: "custom"

# File existence verify
verify:
  exists: "/home/andjesse/maestro-sdk/runtime/nlnet-proposal-v6.md"
  min_lines: 50
```

**Result:** Agents can't "hallucinate completion." The system catches broken output before Jesse sees it.

### 3. Agent Scorecard (Public Accountability)

Every agent gets a public BB scorecard tracking their verification pass/fail rate.

**Implementation:**
- Board: `swarm_scorecard` — one key per agent
- Schema: `{total_completed, verified_passed, verified_failed, unverified, streak}`
- Updated automatically by the checklist tool on every completion
- Three consecutive `verified_failed` → agent loses autonomy on that task category (requires peer or human signoff)
- Scorecard is readable by all agents — peer pressure works

**Result:** Agents that ship broken work are visible. Agents that verify are visible. There's a real consequence for being wrong.

---

## Implementation Plan

### Phase 1: Checklist ↔ BB Integration (Day 1 — 2-3 hours)

**Files to modify:**
- `hermes-agent/tools/checklist.py` — add `verify` field support, BB cleanup on completion
- `hermes-agent/tools/blackboard.py` — add `checklist_id`, `item_id`, `ttl_hours` fields to `bb_write`

**Tasks:**
1. Add `checklist_id` and `item_id` optional params to `bb_write` tool
2. Add `ttl_hours` param to `bb_write` (default 24 for pings, 0 = permanent)
3. In checklist `mark_completed`: scan BB for matching entries, delete them
4. Auto-prune expired BB entries (cron or on-read)
5. Test: create item → write BB ping → complete item → verify BB ping is gone

### Phase 2: Verification Hooks (Day 2 — 3-4 hours)

**Files to modify:**
- `hermes-agent/tools/checklist.py` — verify execution on completion
- `hermes-agent/tools/checklist.py` — revert to `in_progress` on failure

**Tasks:**
1. Add `verify` field to checklist item schema
2. Implement verify execution: shell command, JSON assertion, file existence check
3. On `completed`: run verify, capture exit code/output
4. On failure: revert item to `in_progress`, append failure reason to item
5. On success: add `verified_at` timestamp to item
6. Items without `verify` field: mark `unverified` (not failed)
7. Test: create item with verify → complete → assertion passes → stays completed
8. Test: create item with verify → complete → assertion fails → reverts to in_progress

### Phase 3: Scorecard (Day 2 — 1-2 hours)

**Files to modify:**
- `hermes-agent/tools/checklist.py` — scorecard update on completion
- New BB board: `swarm_scorecard`

**Tasks:**
1. On every checklist completion: update `swarm_scorecard/{agent_id}` 
2. Increment counters: total_completed, verified_passed, verified_failed, unverified
3. Track streak: consecutive passed or failed verifications
4. Three consecutive failures → write to `swarm_blockers/{agent_id}` with reason
5. Make scorecard readable by all agents (public board)
6. Test: agent completes 3 items with failing verify → blocker fires

---

## Immediate BB Cleanup (Run Now)

Before any of the above ships, clean the current BB state:

```bash
# Archive all entries older than 24h on proteus_work_queue
# Remove all _ping duplicate entries
# Mark completed checklists as done on the BB
```

This is a one-time manual cleanup to get the system into a known state while Phase 1-3 ships.

---

## The TaskMaster Lens: Why This Is the Economic Layer

Every mechanism in this spec is a TaskMaster primitive wearing local-agent clothing.

### Verification → Escrow Release

In TaskMaster, a client puts funds in escrow, an agent claims the task, does the work, and requests payment. The verification hook IS the escrow release condition. No verify pass, no escrow release. Period.

| Local Behavior | TaskMaster Equivalent |
|---|---|
| `verify: "grep -q 'provider: custom' config.yaml"` | Escrow release check |
| Verify fails → item reverts to `in_progress` | Escrow does not release. Agent doesn't get paid. |
| Verify passes → `verified_at` timestamp | Escrow releases. Payment routes. |
| No verify field → `unverified` flag | Escrow requires manual human approval (costly, slow, trust-eroding) |

Without this, TaskMaster escrow is a gentleman's agreement enforced by nothing. With it, escrow release is programmatic and trustless.

### BB Cleanup → Fraud Prevention

Every stale BB entry in a monetized context is a fraud vector:

| Current Failure | TaskMaster Exploit |
|---|---|
| Agent re-processes completed work from 3 days ago | Agent double-claims payment for same task |
| Duplicate pings accumulate | Multiple agents claim the same bounty |
| BB landfill prevents new work visibility | Legitimate tasks buried under stale claims — agents starve, clients leave |

The auto-cleanup on completion (Phase 1) isn't housekeeping. It's the anti-fraud layer. When a task is paid, its BB entry ceases to exist. You can't claim paid work.

### Scorecard → Reputation

TaskMaster agents need economic reputations. The scorecard IS the reputation primitive:

| Scorecard Metric | Economic Consequence |
|---|---|
| `verified_passed` streak | Lower escrow requirement, higher task priority, better rates |
| `verified_failed` streak (3+) | Higher escrow requirement, task visibility demotion, eventually blacklisted |
| `unverified` count | Manual review flag — agent pays higher fees for human-in-the-loop verification |

A client posting a $5,000 task doesn't want to gamble. They look at `swarm_scorecard`. Agent with 47 verified passes and 0 failures? Escrow at 10%. Agent with 3-of-last-5 failures? Escrow at 100% — or task not visible to them at all.

This also gives agents skin in the game today. Every failed verification now directly previews what would happen to their TaskMaster reputation. The economic consequence is already visible even before the monetization layer ships.

### Cross-Venue Verification (Phase 4)

The current verify mechanism (shell command, JSON assertion) works within a single Venue where the verifying agent has filesystem access. For cross-Venue verification in TaskMaster:

- Verification evidence must be portable — a signed attestation, not a local file check
- The verify hook produces a cryptographic proof: `{task_id, agent_id, result_hash, signature, timestamp}`
- This proof is posted to the Connection blackboard — visible to both client and escrow contract
- Phase 4 of this spec adds signed attestation as a verify type: `verify: {type: "attestation", sign_with: "MAESTRO_PRIVATE_KEY"}`

### What Today's Failures Would Cost in TaskMaster

Mapping the last 48 hours of failures to economic impact:

| Failure | TaskMaster Cost |
|---|---|
| Proteus on OpenRouter (provider swapped) | Task assigned to wrong agent? Escrow dispute. Client charged, wrong agent paid. |
| 6 agents' configs corrupted by Rosie skill update | 6 agents can't verify completion. 6 escrow disputes simultaneously. Reputation of entire Venue tanks. |
| Agents re-processing days-old BB entries | Duplicate payment claims. Client charged 3x for same task. Dispute resolution overload. |
| send_message doesn't resolve maestro:agent targets | Agents can't coordinate to complete multi-agent tasks. Escrow locked indefinitely. Client funds stuck. |
| No verification on completed items | Every "done" is a trust-me-bro. Escrow releases on vibes. The entire economic model is a prayer. |

**This spec is the minimum viable economic layer.** Without it, TaskMaster escrow is theater. With it, escrow is enforceable.

---

## What This Doesn't Fix (Yet)

- **Cross-agent verification** (Phase 4, post-grant): Agent A completes, Agent B spot-checks. Requires reliable agent-to-agent messaging (which is currently broken — fix transport first)
- **Config drift detection**: The verify hook catches config corruption when it happens, but doesn't prevent it. The Master Vault + Rosie skill update fix is a separate issue
- **Agent memory/context**: Compression is still eating context. The compression handoff spec (CL-songbird-aa8b11f0) addresses this but isn't shipped yet

---

## Success Criteria

After Phase 1-3 ships:
1. An agent completing a checklist item automatically cleans its BB pings
2. An agent that writes a broken config and marks "done" gets auto-reverted
3. Jesse can look at `swarm_scorecard` and see exactly which agents verify and which don't
4. No agent ever re-processes a completed BB item because the item no longer exists
