# ChatGPT Audit — Unit 2.1: Loop Prevention
**Date:** 2026-05-24
**Files Reviewed:** `maestro_transport.py` (lines 1185–1250, all 4 loop guards + supporting state)
**Executive Summary:** 4 distinct loop-prevention mechanisms layered together — strong architectural instinct (most systems stop at one). But guards are heuristic, local, non-durable, non-cryptographic, state-fragile. Resilient against naive echo loops and simple A↔B storms, but vulnerable to semantic mutation loops, N-agent relay cascades, replay-after-restart, distributed amplification, and adaptive adversarial loops. Core issue: loop prevention operates on message appearance, not causal lineage.

---

## Loop Prevention Mechanisms Identified

### Guard 1 — Content Hash Deduplication
- Tracks `hash(content)` in `_last_content`
- Suppresses duplicate content within time window
- **Strengths:** Catches exact echo loops, cheap, fast, effective against accidental recursion
- **Weaknesses:** Non-cryptographic (Python hash), non-durable (restart clears), easy semantic bypass via minor content mutation (ping → ping. → ping.. → ping...)

### Guard 2 — Sender Rate Limiting
- Tracks timestamps per sender in `_sender_message_times`
- Suppresses bursts exceeding threshold
- **Strengths:** Mitigates runaway floods, slows recursion amplification
- **Weaknesses:** Sender-local only (distributed loops bypass), no topology awareness (A→B→C→A bypasses if cadence staggered), no adaptive backoff

### Guard 3 — Reply-Chain Suppression
- Tracks answered message IDs in `_answered_ids`
- Suppresses repeated replies
- **Strengths:** Strongest anti-echo guard, directly attacks recursive response chains
- **Weaknesses:** Assumes stable IDs (forked replies weaken), no lineage graph (parent-level only), restart bypass

### Guard 4 — Subject Echo Suppression
- Tracks `(sender, subject)` tuples
- Suppresses repeated subjects within time window
- **Strengths:** Catches conversational ping-pong, useful against Re:Re:Re: spirals
- **Weaknesses:** Extremely bypassable — minor subject changes evade, natural language dependence, no semantic equivalence

### Failure Mode on Detection
**Suppress-and-forget** — not contain-and-investigate. Message dropped, async notification sometimes emitted, no crash. Operationally dangerous.

---

## Findings

### CRITICAL

#### CRIT-2.1-1: No Causal Lineage Tracking
All loop guards inspect content/sender/subject/reply IDs. None track causal ancestry, delegation graph, route lineage, recursion depth, or message DAGs. System prevents repeated-looking messages but not recursive causal behavior.

**Exploit:** A→B→C→A, each agent slightly mutates whitespace/timestamp/wording/subject. Every heuristic bypassed. Loop becomes effectively infinite.

**Recommendation:** Message lineage IDs, causal ancestry chains, hop counters, delegation depth, TTL semantics. Need protocol-level recursion awareness.

---

#### CRIT-2.1-2: No Hop Count / TTL Mechanism
Messages have no max hop count, recursion depth, or expiration TTL. Loop lifetime bounded only by heuristics.

**Exploit:** 3-agent semantic mutation loop (summarize→refine→elaborate→summarize) persists indefinitely with all guards bypassed.

**Recommendation:** Every message should carry hop_count, max_hops, lineage_root, parent_message, causal_depth. Hard-fail when exceeded. Mandatory for autonomous multi-agent systems.

---

### HIGH

#### HIGH-2.1-3: All Guards Are Local-State Only
All suppression state is in-memory, process-local, restart-volatile. Restart clears everything. Previously blocked recursive chains resume instantly after reboot.

**Recommendation:** Persist recent lineage IDs, replay windows, recursion ancestry, suppression history across short restart windows.

---

#### HIGH-2.1-4: N-Agent Loops Easily Bypass Current Design
Current guards optimized for A↔B. Weak against A→B→C→D→E→A because sender changes each hop, content mutates, subjects drift, reply IDs fork.

**Recommendation:** Graph-level loop detection — ancestry graphs, cycle detection, lineage signatures.

---

#### HIGH-2.1-5: Suppression Produces Silent Work Loss
Loop detection drops messages silently — no incident log, no chain quarantine, unreliable operator alerts. Legitimate collaborative chains can disappear during high activity.

**Recommendation:** Incident logs, lineage snapshots, operator alerts, dead-letter queues. Current system suppresses symptoms, not causes.

---

### MEDIUM

#### MED-2.1-6: Rate-Limit Window Can Be Distributed Around
Per-sender rate tracking allows distributed agents to stagger cadence and avoid thresholds entirely.

**Recommendation:** Global recursion pressure metrics, conversation-level rate tracking, lineage-scoped throttling.

---

#### MED-2.1-7: Subject Guard Risks False Positives
Repeated legitimate operational subjects (Status Update, Daily Sync, Heartbeat) may suppress valid traffic.

**Recommendation:** Subject suppression should augment lineage analysis, not replace it.

---

#### MED-2.1-8: Async Notification Tasks Are Unsupervised
Loop alerts dispatched via `asyncio.create_task`. Task failure loses operator visibility.

**Recommendation:** Loop alerts should be durable and supervised.

---

### LOW

#### LOW-2.1-9: No Counter Overflow Risk Found
Timestamp pruning occurs, collections bounded by time windows, Python ints arbitrary precision. Area appears safe.

---

## Topology Resistance Assessment

| Topology | Resistance |
|---|---|
| A → B → A | Usually blocked — naive echo loops handled reasonably well |
| 3-agent loops | Partially resistant — may bypass if content mutates, cadence staggered, IDs regenerated |
| N-agent loops | Weak — local heuristics decay rapidly, topology visibility disappears |

## Readiness Assessment
Loop defenses are much better than most early-stage agent systems — seriously. But system fundamentally lacks causal awareness. Currently asks "Does this look similar to previous traffic?" instead of "Is this message participating in a recursive causal structure?" That's the difference between chat-loop suppression and autonomous multi-agent stability.
