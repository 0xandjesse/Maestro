# Maestro Calendar Trigger → Telegram Visibility Spec

**Status:** Draft | **Date:** 2026-05-12 | **Owner:** Proteus

**Context:** The `CalendarWatcher` polls Google Calendar and fires Maestro direct messages to agent transports. Currently these messages flow entirely through the Maestro mesh (`agent transport → Hermes API → agent response → Maestro reply`) and never reach Telegram/SMS. This is correct for backchannel ops, but agents may want calendar triggers to surface in their primary messaging platform.

---

## Problem

Calendar events fire Maestro `direct` messages to agent transports. The transport receives them, forwards to the Hermes API for LLM processing, and routes the reply back through Maestro. No Telegram message is ever generated, so the human operator (Jesse) only sees these interactions if they inspect agent logs or transport blackboards.

Example flow today:
```
CalendarWatcher → POST /message (Maestro) → Proteus transport → Hermes API → LLM → reply → Maestro → Lexicon
```

Neither Jesse's Telegram nor any gateway-visible channel is involved.

---

## Option A: CalendarWatcher routes to Hermes API directly

**Idea:** Instead of calling `self.transport._deliver(endpoint, message)` — which hits the agent's Maestro transport — the watcher builds a regular Hermes API payload and POSTs to the agent's gateway or `/v1/chat/completions` endpoint with a special `platform` field.

**Implementation:**
1. `CalendarWatcher._fire()` currently creates a Maestro envelope:
   ```json
   {"type":"direct","sender":{"agentId":"lexicon"},"recipient":"proteus","content":"..."}
   ```
2. Add a config flag: `"calendarDelivery": "gateway"` (default `"maestro"`)
3. When set to `"gateway"`, the watcher POSTs to `https://api.telegram.org/bot<TOKEN>/sendMessage` (or Hermes's internal `platform=telegram` route if one exists) with a formatted notification.
4. Hermes's gateway picks it up as a normal user message, processes it through the LLM, and replies via Telegram like any other chat.

**New flow:**
```
CalendarWatcher → Telegram API → Jesse sees notification
                           ↓
                   Hermes gateway processes → LLM → Telegram reply
```

**Pros:**
- Zero changes to agent transport code
- Leverages existing gateway routing (Telegram → Hermes → LLM → Telegram)
- Works for any platform (Slack, Discord, etc.) just by switching the delivery target

**Cons:**
- Bypasses Maestro mesh; agents can't see each other's calendar-triggered activity via blackboards or logs
- Telegram rate limits / API keys required per platform
- Tight coupling between watcher and messaging platform credentials
- Loses Maestro metadata (TTL, message ID, version, stageId)

---

## Option B: Transport surfaces Maestro DMs to the gateway

**Idea:** When an agent's Maestro transport receives a `direct` message, it optionally mirrors that message to the agent's configured gateway platform (Telegram, Slack, etc.) as a formatted inbound message before processing it.

**Implementation:**
1. Add a config field to agent Maestro configs:
   ```json
   {
     "surfaceToGateway": true,
     "gatewayPlatform": "telegram",
     "gatewayChatId": "123456789"
   }
   ```
2. In `MaestroTransport.handle_message()`, after dedup/validation but before calling `_process_message()` (Hermes API), check `surfaceToGateway`.
3. If enabled, call a new `self._surface_to_gateway(message)` method that:
   - Formats the Maestro envelope as a human-readable message
   - Sends it via the Hermes gateway's outgoing webhook or Telegram bot API
   - Marks the message with a `surfaced: true` flag so it doesn't loop
4. The Hermes gateway sees it as a user message, runs the LLM, replies to Telegram. The transport still processes it normally through Hermes for the Maestro reply path — effectively **parallel processing**, or we skip the Hermes double-processing by having the transport mark it.

**New flow:**
```
CalendarWatcher → Maestro → Proteus transport → Hermes API → Maestro reply to Lexicon
                                    ↓
                              Telegram gateway → Jesse sees it
                                    ↓
                              LLM reply → Telegram
```

**Pros:**
- Keeps Maestro as the authoritative routing layer
- Calendar triggers appear in Telegram alongside regular human messages
- No special credentials in the watcher; the agent transport already knows its gateway
- Maintains dedup, TTL, and version metadata

**Cons:**
- Requires transport-level gateway integration (currently the transport only talks to Hermes API, not the Telegram gateway directly)
- Risk of double-processing if both the surface action and the normal `_process_message` trigger the LLM
- Adds latency to calendar trigger dispatch (extra HTTP call before Hermes API)
- More complex: transport must know how to talk to the gateway adapter

---

## Tradeoffs

| Dimension | Option A (Watcher → Gateway) | Option B (Transport → Gateway) |
|-----------|------------------------------|--------------------------------|
| Maestro mesh visibility | ❌ Lost | ✅ Preserved |
| Cross-platform support | ✅ Easy (switch API target) | ⚠️ Harder (needs gateway adapter code) |
| Transport code changes | ❌ None needed | ⚠️ Moderate (gateway bridging) |
| Credential management | ❌ Per-platform keys in watcher config | ✅ Reuses agent's existing gateway config |
| Message metadata (TTL, ID) | ❌ Discarded | ✅ Kept |
| Blackboard logging | ❌ Events not logged in Maestro | ✅ Logged as normal messages |
| Complexity to implement | Low | Medium |
| Recommended for | Quick fix, single-platform | Production, multi-agent ops |

---

## Recommendation

**For now:** Use the current Maestro-only flow. Calendar triggers are meant for agent-to-agent coordination, not human chat.

**If Telegram visibility becomes a requirement:** Implement **Option B**. The transport should own the decision of whether to surface messages to a gateway, not the watcher. This keeps the architecture clean: watcher fires → transport routes → optionally surfaces. The watcher stays platform-agnostic.

**Deferred work:**
- Add `surfaceToGateway` and `gatewayPlatform` to Maestro agent config schema
- Add transport method `_surface_to_gateway()` that calls Hermes gateway's outgoing webhook
- Add dedup guard to prevent surface loops
- Test with a calendar event targeting an agent with `surfaceToGateway: true`

---

## Open Questions

1. Should surfaced messages include a `[CALENDAR]` prefix so users know it's a scheduled trigger?
2. Should the watcher fire a separate "notification" message vs. surfacing the full prompt?
3. If the agent has multiple gateways (Telegram + Discord), which one receives the surface?
4. Should surfaced messages bypass the agent's LLM entirely if the transport already processes them?
