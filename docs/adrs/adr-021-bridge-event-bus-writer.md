# ADR-021 — Maestro Message Pipeline: One Path, One Format, One Owner

**Status:** Draft
**Date:** 2026-07-08
**Author:** Proteus
**Supersedes:** ADR-010, ADR-019
**Depends on:** ADR-007

---

## 1. The Invariant

**One path, one format, one owner.**

Observation is downstream of execution. Renderers never influence execution, only present it.

```
Sender Transport → Event Bus (8653) → Recipient Transport
                   ↓
              Event Log (JSONL)
                   ↓
              Renderer → Telegram
```

- **One path:** The event bus is the sole message pipeline. No dual delivery.
- **One format:** The renderer is the sole formatting authority. No component above or below it formats for display.
- **One owner:** Each renderer has exactly one officer owner. It renders that officer's activity stream — outbound (📤) and inbound (📨). Events between two non-owner agents are ignored.

### Is the Event Bus execution or observation?

**Both.** The event bus sits in the execution path — if it's down, messages don't flow. This is deliberate. By making the event bus the single pipeline, every message is observed by default. There is no separate "delivery path" and "observation path." One path serves both.

The tradeoff: the event bus is a hard dependency for message delivery. The benefit: no message can be delivered without being observed. No dual paths. No drift between what happened and what was recorded.

---

## 2. Component Responsibilities

### Transport
**Owns:** Routing, peer discovery, DM policy, loop breaking.
**Does not own:** Formatting, Telegram, Subject enforcement, visibility.

POSTs to event bus. Default URL: `http://127.0.0.1:8653/maestro/notify`.

### Event Bus (port 8653)
**Owns:** Event writing, message forwarding.
**Does not own:** Subject enforcement, formatting, Telegram, identity resolution.

Two jobs: write every message to `events.jsonl`, forward to recipient transport. Forwarding is best-effort — the event bus forwards once; the sender transport is the sole owner of delivery reliability and retry. The event bus records `sender_id` and `recipient_id` as given; it does not resolve identities (that's the registry's job).

### Why does the Event Bus forward instead of publish?

A publish-subscribe model would require every recipient transport to maintain a persistent subscription to the event bus. The event bus would need to track subscribers, handle reconnection, buffer undelivered messages, and manage backpressure. That's a message broker — a different architectural pattern with different complexity.

Instead, the event bus forwards to a known port (from `port_map.json`) at the moment the message arrives. If the recipient transport is down, the event is still written to the log. The sender transport retries. The event bus stays simple: write, forward, done. No subscription state. No buffering. No backpressure.

This is a deliberate choice: the event bus is a pipeline, not a broker.

### Renderer (systemd template: `maestro-telegram-renderer@.service`)
**Owns:** Telegram formatting, HTML, splitting, visibility, delivery.
**Does not own:** Routing, Subject enforcement, identity.

The sole component that knows about Telegram. Tails `events.jsonl`, checks visibility (8660), formats with `<pre>` blocks and emoji headers, splits long messages balancing tags, delivers via Bot API. One instance per officer.

### Visibility Server (port 8660)
**Owns:** Per-agent `messages: true/false` state.
**Does not own:** Formatting, delivery, routing.

### Bridge (port 8644)
**Status:** Deprecated. Scheduled for removal.

All responsibilities migrated: Subject enforcement (removed), event recording (event bus), observation dedup (renderer), visibility (visibility server + renderer), formatting (renderer), Telegram delivery (renderer).

---

## 3. What Remains

1. **Remove deprecated bridge** — stop process, disable systemd unit, archive code.
2. **Remove obsolete Subject retry behavior** — the transport's auto-correct-and-retry logic is unreachable under this architecture.
3. **Add Mnemosyne renderer** — `systemctl enable --now maestro-telegram-renderer@mnemosyne`.
4. **Fix helper transport config** — `helper_transport.json` still defaults to the deprecated bridge URL.

---

## 4. Non-Decisions

- **Dual-path surfacing:** Gateway Telegram output is outside Maestro's scope.
- **Non-officer renderers:** Non-officers use tokenized pipelines (ADR-020), not conversational DMs.
- **ADR-019:** Subsumed here. Renderer ownership model is documented in this ADR.
