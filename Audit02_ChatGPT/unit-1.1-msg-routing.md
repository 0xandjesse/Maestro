# ChatGPT Audit — Unit 1.1: Message Routing Core
**Date:** 2026-05-24
**Files Reviewed:** `maestro_transport.py` (lines 1175–1362)
**Executive Summary:** Routing core is conceptually clean but behaves as a best-effort conversational relay, not a hardened messaging substrate. The transport has no durable concept of message state.

---

## Findings

### CRITICAL

#### CRIT-1.1-1: Silent Message Loss Across Multiple Failure Paths
Messages are discarded silently in 6+ branches:
- billing suppression
- duplicate suppression
- rate limit suppression
- reply-chain suppression
- no Hermes output
- nonexistent sender registry
- failed outbound delivery

Most paths: no sender notification, no persistence, no retry, no telemetry.

**Exploit:** Malicious agent floods another with repeated content. Transport begins silently suppressing legitimate work as "loop behavior." No failures visible to human operators — covert denial-of-service.

**Recommendation:** Dead-letter queue, durable suppression audit log, structured failure events, sender-visible rejection semantics, message lifecycle state machine (RECEIVED → SUPPRESSED → PROCESSING → FAILED → RETRY_PENDING → DELIVERED).

---

### HIGH

#### HIGH-1.1-2: Python `hash()` Used for Deduplication
`content_hash = hash(content)` — Python hash randomization makes hashes process-specific, unstable across restarts, and collision-prone. Not suitable for protocol semantics.

**Recommendation:** SHA-256 or BLAKE3 with canonicalized payload hashing.

---

#### HIGH-1.1-3: Fire-and-Forget Async Tasks Can Vanish
`asyncio.create_task(...)` used without task tracking, cancellation handling, or exception collection. Crashes disappear silently.

**Recommendation:** Supervised task groups with registry, structured concurrency, timeout policy, retry semantics, exception harvesting.

---

#### HIGH-1.1-4: Offline/Nonexistent Agent Handling Is Weak
Registry lookup fails → warning + return. HTTP delivery fails → error logged. No persistence, retry queue, backoff, health tracking, or circuit breaker.

**Recommendation:** Durable outbound queue, retry with exponential backoff, endpoint health scoring, circuit breaker, offline mailbox semantics.

---

### MEDIUM

#### MED-1.1-5: Race Conditions Around Shared Mutable State
`_last_content`, `_answered_ids`, `_sender_message_times`, `_sent_subjects` mutated without synchronization. Under high concurrency: nondeterministic suppression, state drift.

**Recommendation:** asyncio locks, actor-style ownership, immutable snapshots, dedicated routing state manager.

---

#### MED-1.1-6: Overbroad Billing Error Suppression
Any message containing `"402"` can be dropped. Legitimate content about HTTP semantics, RFCs, diagnostics vanishes.

**Recommendation:** Structured error typing, protocol metadata, explicit machine-readable error codes. Never content-scan free text for transport control decisions.

---

#### MED-1.1-7: Directive Semantics Create Orphaned Execution
Directive replies intentionally suppressed. No completion ACK, timeout visibility, execution receipt, or guaranteed closure.

**Recommendation:** Execution receipts, completion tokens, directive state tracking, explicit success/failure envelopes.

---

### LOW

#### LOW-1.1-8: Exception Swallowing Hides Operational Truth
Bridge mirror: `except Exception: pass`. Destroys observability.

**Recommendation:** Structured warning log, metrics counter, failure event emission.

---

## Readiness Assessment
Not yet ready as a hardened messaging system. The transport has no durable concept of message state. Without durable queues, retries, audit trails, and structured failure semantics, the system can lose work invisibly under realistic adversarial conditions.
