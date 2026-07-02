# ChatGPT Audit — Unit 2.4: Cooldown & Shutup Mechanisms
**Date:** 2026-05-24
**Files Reviewed:** `maestro_transport.py` (shutup/cooldown mechanisms)
**Executive Summary:** The cooldown/shutup system is a proto-immune-system for runaway agents — good instinct. But it behaves as heuristic behavioral punishment rather than governed transport-control. Biggest issues: agents can be silenced based on emergent behavior without strong causal attribution (false positives, distributed blame bleed, coordinated silencing), and cooldown state is mostly ephemeral (restart resets protections, adversarial restart becomes useful). Suppresses symptoms without accountable enforcement, escalation policy, recovery governance, or operator authority model.

---

## Mechanisms Identified

1. **Sender Rate Suppression** — `_sender_message_times`, excessive sender activity suppressed
2. **Subject Repetition Suppression** — `_sent_subjects`, repeated subject traffic triggers suppression
3. **Duplicate Content Suppression** — repeated content hashes trigger drops
4. **Reply-Chain Suppression** — repeated reply behavior blocked

---

## Findings

### CRITICAL

#### CRIT-2.4-1: No Strong Attribution Model — Agents Silenced by Emergent Behavior
Suppression attributes problematic behavior to sender/content/subject but not causal origin, delegation ancestry, triggering requester, or recursive chain ownership.

**Exploit (Delegation Framing):** Attacker → Agent B → Agent A. Attacker repeatedly causes Agent B to provoke Agent A into mirrored responses. Agent A accumulates suppression triggers and gets silenced despite not originating recursion. Well-behaved agents become operationally muted due to downstream adversarial orchestration.

**Recommendation:** Causal attribution model — lineage root, delegation ancestry, initiator identity, causal blame assignment. Suppression should target recursion source, not just visible participant.

---

#### CRIT-2.4-2: No Governance Layer for Silencing Decisions
Suppression is automatic and heuristic-driven. No operator confirmation, escalation review, quarantine state, appeals/recovery workflow, or policy tiering. Transport autonomously decides which agents deserve speech suppression — dangerous in sovereign multi-agent governance.

**Recommendation:** WARN → THROTTLE → COOLDOWN → QUARANTINE → HUMAN_REVIEW with explicit transitions. Current model jumps directly from normal to silently suppressed.

---

### HIGH

#### HIGH-2.4-3: Suppression State Is Non-Durable Across Restarts
Cooldown state entirely in memory. Restart resets all protections. Recursive storm begins, attacker forces transport restart, all suppression memory erased, storm resumes immediately.

**Recommendation:** Persist suppression windows, offender state, lineage penalties, cooldown timers across reboot windows.

---

#### HIGH-2.4-4: Agents Can Be Soft-Silenced Indefinitely
Repeated normal operational patterns may continuously retrigger suppression. No decay governance. High-volume useful agents accumulate behavioral debt forever — chronic degradation.

**Recommendation:** Decaying penalties, forgiveness windows, reputation recovery, adaptive thresholds.

---

#### HIGH-2.4-5: No Explicit Human Override Path Found
No authoritative `unsilence()`, `force_release()`, or `operator_override()` mechanism. Human operators cannot deterministically recover muted agents, poisoned suppression state, or false positives without restarting transport.

**Recommendation:** Operator console, override API, signed administrative release, suppression inspection tooling. Autonomous suppression without human override becomes governance-dangerous.

---

#### HIGH-2.4-6: Suppression Can Be Triggered Indirectly via Content Injection
Content-based suppression means attackers can intentionally induce repetitive patterns ("Please reply with EXACTLY this payload..."). Repeated externally induced outputs poison suppression heuristics.

**Recommendation:** Suppression should weigh intent, lineage, conversation structure, initiator identity — not raw content repetition alone.

---

### MEDIUM

#### MED-2.4-7: Cooldown Semantics Are Implicit, Not Explicit
No formal cooldown object/state — suppression emerges indirectly from heuristic structures. No inspection, timers, auditability, or policy introspection.

**Recommendation:** Explicit suppression entities — `agent_id`, `reason`, `severity`, `expires_at`, `source_lineage`, `review_status`.

---

#### MED-2.4-8: Notification Reliability Is Weak
Loop/suppression alerts dispatched via `asyncio.create_task`. Failures disappear silently. Operators may never learn suppression occurred.

**Recommendation:** Suppression events should be durable operational incidents.

---

#### MED-2.4-9: Shared-State Mutation Still Race-Prone
Suppression structures mutate asynchronously without transactional guarantees — may drift under concurrency causing premature unsuppression or accidental over-suppression.

**Recommendation:** Transactional consistency for suppression state mutations.

---

### LOW

#### LOW-2.4-10: No Permanent Hard Ban Mechanism Detected
Good news: no obvious irreversible ban state. Suppression appears window-based, reducing catastrophic lockout risk.

---

## Human Override Assessment
**Weak / implicit only.** Practical override is restart transport — not sufficient governance tooling.

## Restart Persistence
Mostly ephemeral — suppression state does NOT survive restart. Creates both recovery path and attack surface.

## Readiness Assessment
Surprisingly solid proto-immune-system for early agent fabric. But operates through local heuristics and memory pressure rather than accountable causal governance. Key shift needed: move from "this message pattern looks suspicious" to "this causal actor is destabilizing the network" — the point where suppression becomes explainable, governable, recoverable, and resistant to adversarial manipulation.
