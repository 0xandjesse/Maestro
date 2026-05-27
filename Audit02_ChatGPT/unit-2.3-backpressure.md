# ChatGPT Audit — Unit 2.3: Backpressure & Rate Limiting
**Date:** 2026-05-24
**Files Reviewed:** `maestro_transport.py`, `send_message_tool.py`
**Executive Summary:** Transport is asynchronous but not flow-controlled. Uses async request handling and lightweight suppression heuristics, but no true backpressure, bounded queues, admission control, transport fairness, or congestion collapse protection. Under moderate load: probably fine. Under adversarial/pathological load: can be resource-starved or destabilized. Biggest issue: no authoritative queueing model — messages enter directly into execution.

---

## Current Message Handling Model
Messages flow: incoming → `_process_message()` → `await hermes.send_and_complete()` → direct outbound HTTP POST. No central dispatcher queue exists. Messages processed inline per coroutine.

---

## Findings

### CRITICAL

#### CRIT-2.3-1: No Bounded Queue / No Backpressure System
No central queue, bounded work pool, max inflight count, congestion management, or admission control. 1000 simultaneous messages = 1000 simultaneous processing tasks. Buggy agent flooding 100k messages attempts to process everything concurrently — memory exhaustion, event-loop starvation, CPU thrash, socket exhaustion.

**Recommendation:** Bounded async queues, worker pools, priority classes, admission control, congestion collapse protection. Minimum: `asyncio.Queue(maxsize=N)` must exist somewhere authoritative.

---

#### CRIT-2.3-2: Hermes Calls Can Become Unbounded Concurrency Sink
Core path `await self.hermes.send_and_complete(message)` with no semaphore, concurrency limit, timeout envelope, or cancellation policy. 1000 simultaneous recursive delegations = 1000 model calls, giant context builds, runaway memory. Transport self-DOSes.

**Recommendation:** Wrap model execution with `asyncio.Semaphore(MAX_MODEL_CONCURRENCY)` plus execution timeout, cancellation handling, queue pressure metrics.

---

### HIGH

#### HIGH-2.3-3: Rate Limiting Is Sender-Local Only
Current throttling tracks `_sender_message_times` per sender only. No global, conversation, message-type, or route limits. 20 agents each below threshold still overwhelm transport.

**Recommendation:** Layered quotas — per-agent, per-lineage, per-conversation, global transport, per-message-type.

---

#### HIGH-2.3-4: No Fairness Scheduling
All tasks compete equally. No QoS or prioritization. Low-value chatter can starve human directives, critical alerts, coordination messages.

**Recommendation:** Priority lanes: CRITICAL, INTERACTIVE, BACKGROUND, BULK, SYSTEM.

---

#### HIGH-2.3-5: Malicious Agent Can DoS Entire System
Architecture assumes cooperative agents. No agent quotas, execution budgets, resource accounting, or transport isolation. Single compromised agent floods, triggers recursive delegation, forces model saturation — others become unusable.

**Recommendation:** Agent quotas, execution budgets, concurrency ceilings, circuit breakers, offender isolation.

---

#### HIGH-2.3-6: Outbound HTTP Calls Lack Robust Timeout Governance
aiohttp timeout wrappers used inconsistently. DNS/socket/TLS stalls accumulate. Large numbers of stalled sockets exhaust file descriptors.

**Recommendation:** Every external call needs connect timeout, read timeout, total timeout, retry budget, circuit breaker.

---

### MEDIUM

#### MED-2.3-7: No Overflow Behavior Exists Because No Queue Exists
Overload propagates directly into coroutine explosion, memory growth, transport instability.

**Recommendation:** Explicit overload behavior — reject, defer, shed, downgrade, spill-to-disk.

---

#### MED-2.3-8: Fire-and-Forget Tasks Amplify Pressure
Bridge/alert tasks via `asyncio.create_task` with no supervision. Under flood, task counts explode.

**Recommendation:** Supervised task groups, bounded worker pools, structured concurrency.

---

#### MED-2.3-9: No Message Cost Accounting
Tiny heartbeat and giant payload treated identically. Large prompts disproportionately consume capacity.

**Recommendation:** Weighted scheduling.

---

#### MED-2.3-10: Dedup State Can Grow Under Adversarial Mutation
Adversarial unique-message floods cause state churn in suppression caches.

**Recommendation:** Bounded LRU structures, memory caps, eviction telemetry.

---

### LOW

#### LOW-2.3-11: Async Architecture Is Fundamentally Correct Direction
Positive: transport already async-native — viable foundation for worker pools, queues, structured concurrency, backpressure. Retrofitting sync code would be far worse.

---

## Readiness Assessment
Transport behaves like an async conversational fabric, not yet a resilient distributed message bus. Key missing concept: pressure-aware scheduling. Every message implicitly deserves immediate execution — that assumption collapses under scale. Approaching the point where Maestro needs a dispatcher, worker pools, queue semantics, QoS tiers, resource accounting, and congestion policy.
