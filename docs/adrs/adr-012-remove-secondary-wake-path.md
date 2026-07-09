# ADR-012: Remove Secondary Wake Path — Bridge Must Not Wake Gateway

**Status:** Superseded by ADR-021 (Message Pipeline: One Path, One Format, One Owner) — the old bridge no longer exists; renderers are pure observers
**Date:** 2026-07-05
**Author:** Proteus
**Reviewer:** Sentinel (pending)

---

## Context

The transport's `_surface_to_gateway` method (lines 2004-2009) includes `gateway_api_url` and `gateway_api_key` in the payload sent to the bridge. The bridge uses these credentials to re-inject messages into the agent's LLM gateway as a "secondary wake path" — a fallback for when the transport's primary processing path (`send_and_complete`) times out or fails.

This creates an architectural violation: the bridge, whose job is to render messages to a surface (Telegram), is also capable of waking the gateway and re-injecting messages into the LLM processing pipeline. The bridge is making transport-level decisions. The transport is leaking gateway credentials across a module boundary.

## Observed Behavior

The secondary wake path was implicated in the duplicate-message investigation of 2026-07-05. The observed message path during duplication was:

```
Lex → Transport → Gateway → Bridge → Gateway → Transport → Songbird
                                    ↑
                              secondary wake path
```

The bridge re-injected the message into the gateway, which fed it back to the transport, which surfaced it again. This created a feedback loop that produced duplicate deliveries.

## Decision

**Remove the secondary wake path from the bridge entirely.** The bridge becomes a pure renderer: it receives facts, surfaces them to Telegram, and does not act on them. All retry, dead-letter, and wake logic moves to the transport layer where it belongs.

### What changes

1. **Transport `_surface_to_gateway`**: Remove `gateway_api_url` and `gateway_api_key` from the bridge payload. The bridge no longer receives credentials.

2. **Bridge `_notify_handler`**: Remove any gateway-wake logic. The bridge only renders to Telegram. If rendering fails, it logs and moves on.

3. **Transport dead letter retry**: The transport already has a dead letter queue (`~/.maestro/dead_letter/{agent_id}.jsonl`). A transport-owned watchdog (separate from the bridge) will retry dead letters on a schedule. This replaces the secondary wake path with a properly-owned retry mechanism.

4. **No new module**: The dead letter watchdog lives in the transport process — no new service, no new port. It's a background task that polls the dead letter queue and retries.

### What stays the same

- The bridge continues to render messages to Telegram.
- The bridge continues to enforce Subject line requirements.
- The bridge continues to deduplicate by subject within a sliding window.
- The transport continues to own message routing, ACKs, and delivery.

## Architectural Principle

> **Renderers are windows, not controllers.** (ADR-007, ADR-010)
>
> The bridge observes and reports. It does not act. It does not wake. It does not retry. It does not inject. It surfaces facts and stops.

This principle is now explicit and enforceable. Any future change that gives the bridge agency over message flow is a boundary violation.

## Trust Surface Impact

This change directly protects the Trust Surface:

| Check | Before | After |
|-------|--------|-------|
| Exactly one message delivered | ❌ Bridge could re-inject, creating duplicates | ✅ Bridge cannot re-inject |
| No phantom retries | ❌ Bridge could wake gateway at any time | ✅ Only transport retries, on a defined schedule |
| No duplicates | ❌ Feedback loop possible | ✅ Single path: transport → bridge → surface |

## Alternatives Considered

### A. Keep secondary wake path, add more dedup
Rejected. This treats the symptom (duplicates) rather than the cause (architectural ambiguity). Adding more dedup layers increases complexity without fixing the ownership problem.

### B. Move secondary wake path to a separate service
Rejected. Adds a new service for a function that belongs in the transport. The transport already has a dead letter queue — the retry logic should live alongside it.

### C. Remove secondary wake path with no replacement
Rejected. Dead letters are a real problem. The transport needs a retry mechanism. But it should be transport-owned, not bridge-owned.

## Consequences

- **Positive**: Single canonical message path. No feedback loop possible. Clear module boundaries. Bridge is simpler and easier to reason about.
- **Negative**: Dead letter retry moves from bridge (which had gateway access) to transport (which needs its own retry schedule). This is a one-time implementation cost.
- **Neutral**: The bridge loses a capability it should never have had.

## Implementation

1. Remove `gateway_api_url` and `gateway_api_key` from transport `_surface_to_gateway` payload (lines 2008-2009, 2018-2019).
2. Remove gateway-wake logic from bridge `_notify_handler`.
3. Add dead letter retry background task to transport: polls `~/.maestro/dead_letter/{agent_id}.jsonl` every 60s, retries up to 3 times with exponential backoff.
4. Update Trust Surface test suite to verify single-path delivery.

## Verification

- Trust Surface test: send message, verify exactly one delivery, verify no phantom retries.
- Manual: send message while gateway is down, verify dead letter queued, bring gateway up, verify retry delivers exactly once.
