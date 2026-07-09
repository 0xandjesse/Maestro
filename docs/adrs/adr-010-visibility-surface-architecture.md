# ADR-010: Visibility Surface Architecture — Split Bridge into Event Bus, Visibility, and Renderers

**Status:** Superseded by ADR-021 (Message Pipeline: One Path, One Format, One Owner)
**Date:** 2026-07-04
**Author:** Proteus (Tech Lead)
**Deciders:** Jesse (CEO), Songbird (CTO), Proteus (Tech Lead)
**Supersedes:** ADR-007 (visibility modes — absorbed), ADR-009 (bridge-to-transport push — absorbed)

---

## Context

The Maestro Gateway Bridge (`maestro_gateway_bridge.py`, port 8644) is a 539-line monolith that does four unrelated things:

1. **Routing** — receives transport POSTs, resolves identities, pushes to recipient transports
2. **Formatting** — builds Telegram messages with emoji, code blocks, subject extraction
3. **Lifecycle** — manages its own process, no systemd unit, manual start
4. **Configuration** — reads/writes `bridge_visibility.json`, `contacts.json`, `port_map.json`, per-agent `.env` files

This is a single point of failure. If the bridge dies, ALL agents lose Telegram visibility. It has no systemd unit — a machine reboot kills it permanently until someone remembers to restart it. It has accumulated responsibilities that belong to different architectural concerns.

Jesse's directive (2026-07-04): the bridge should be split into independent modules following the same separation-of-concerns pattern used throughout Maestro. Transport delivers messages. Visibility decides what to surface. Renderers decide how to present. These are three different jobs.

Additionally, Jesse's Concerto vision requires a renderer-agnostic event stream — the same events that drive Telegram notifications must also drive CLI monitors, web dashboards, VR interfaces, and the Office Simulator UI. The bridge as written cannot support this because Telegram formatting is baked into the notification handler.

---

## Decision

### 1. Four Independent Concerns

```
Transport        →  moves authenticated messages from A to B
Event Bus        →  records facts, not interpretations (agent-agnostic)
Visibility       →  decides what to surface to whom (subsystem of Observability)
Renderer         →  decides how to show it (Telegram, CLI, Concerto, Dashboard)
```

**Observability** is the broader concern. Visibility is one subsystem. Logging, tracing, and metrics are others. This ADR establishes Visibility as the first Observability subsystem; the architecture accommodates the others as they emerge.

**Transport** does not change. It already POSTs to the bridge. It will continue POSTing to the event bus — same endpoint, same payload format. No transport restart required.

**Event Bus** is a new, minimal process. It receives transport POSTs at `/maestro/notify`, validates sender identity, resolves target, and writes a structured event to an append-only event log (`~/.maestro/events/events.jsonl`). It also pushes the message to the recipient's transport (ADR-009 functionality, preserved). It does NO formatting, NO Telegram delivery, NO visibility checks. It records facts, not interpretations — "Task Assigned," not "Urgent Task." Renderers can color it red later. The Event Bus is the nervous system of Maestro: it doesn't decide, it doesn't reason, it simply says "this happened." Everything else reacts.

**Visibility** is a new, minimal process. It reads `bridge_visibility.json` and exposes a query endpoint: `GET /visibility/{agent_id}` returns the agent's mode. It also accepts `POST /visibility` to set modes (slash command handler). It does NO formatting, NO Telegram delivery, NO event processing. It is purely a mode store with an HTTP API.

**Telegram Renderer** is a new process. It tails the event bus JSONL file, checks visibility for each event's participants, formats messages per ADR-007 spec, and delivers via Telegram Bot API. It is the ONLY component that knows about Telegram — bot tokens, chat IDs, Markdown formatting, rate limiting. If someone builds a Discord renderer tomorrow, it reads the same event stream and applies its own formatting.

### 2. Event Schema

Every event written to the JSONL file has this structure:

```json
{
  "id": "evt_abc123",
  "ts": "2026-07-04T22:15:00Z",
  "type": "message",
  "sender": {"agent_id": "lexicon", "name": "Lexicon"},
  "recipient": {"agent_id": "proteus", "name": "Proteus"},
  "msg_type": "direct",
  "content": "Subject: Status check\n\nAll transports green.",
  "subject": "Status check",
  "checklist_id": null,
  "item_id": null,
  "artifacts": [],
  "summary": ""
}
```

The event is agent-agnostic. It contains everything a renderer needs to decide how to present it. No Telegram-specific fields. No formatting. Raw data.

### 3. Component Boundaries

| Component | Knows About | Does NOT Know About |
|-----------|-------------|---------------------|
| Transport | Messages, tokens, ports | Telegram, visibility, formatting |
| Event Bus | Events, identity, transport push | Telegram, visibility, formatting |
| Visibility | Agent modes, slash commands | Telegram, events, formatting |
| Telegram Renderer | Events, visibility, Telegram API | Transport, tokens, ports |

### 4. File Layout

```
~/.maestro/
├── events/
│   └── events.jsonl          # Event bus output (append-only)
├── bridge_visibility.json     # Visibility state (existing, unchanged)
├── contacts.json              # Identity resolution (existing, unchanged)
├── port_map.json              # Transport port registry (existing, unchanged)
│
├── event_bus.py               # NEW: receives POSTs, writes events, pushes to transport
├── visibility_server.py       # NEW: mode store with HTTP API
├── telegram_renderer.py       # NEW: tails events, formats, delivers to Telegram
│
├── systemd/
│   ├── maestro-event-bus.service      # NEW
│   ├── maestro-visibility.service     # NEW
│   └── maestro-telegram-renderer.service  # NEW
│
└── archive/
    └── maestro_gateway_bridge.py  # MOVED: the old monolith, kept for reference
```

### 5. Endpoints

**Event Bus** (port 8644 — same port, same endpoint, zero transport changes):
- `POST /maestro/notify` — receive transport notification, write event, push to recipient transport
- `GET /health` — health check

**Visibility Server** (port 8660):
- `GET /visibility/{agent_id}` — get mode for agent
- `POST /visibility` — set mode for agent (body: `{"agent_id": "songbird", "mode": "full"}`)
- `GET /health` — health check

**Telegram Renderer** (no HTTP server — it's a consumer, not a producer):
- Tails `events.jsonl`
- Queries visibility server for each event's participants
- Delivers to Telegram

### 6. Slash Command Flow (Updated)

Current flow: slash command → bridge `/maestro/visibility` endpoint → bridge writes `bridge_visibility.json`.

New flow: slash command → visibility server `POST /visibility` → visibility server writes `bridge_visibility.json`.

The slash command skills (`maestrofull`, `maestroshort`, `maestrooff`) change their curl target from port 8644 to port 8645. That's a one-line change per skill.

### 7. What Happens to the Old Bridge

`maestro_gateway_bridge.py` is moved to `~/.maestro/archive/` and its process is killed. It is replaced by three processes, each with a systemd unit. The old bridge is kept for reference — it contains the checklist formatting logic that the Telegram renderer will replicate.

---

## Implementation Plan

### Phase 1: Event Bus (`event_bus.py`)

Extract the identity resolution, event writing, and transport push from the bridge. No formatting. No Telegram.

**File:** `~/.maestro/event_bus.py`

**Responsibilities:**
- `POST /maestro/notify` — validate sender, resolve identities, write event to JSONL, push to recipient transport
- `GET /health` — return `{"ok": true, "service": "maestro-event-bus"}`
- Identity resolution via `contacts.json` (copy `resolve_name`, `resolve_uid` from bridge)
- Transport push via `port_map_loader` (copy `_push_to_transport` from bridge)
- Subject extraction for event schema (copy `_extract_subject` from bridge)
- Subject-line enforcement (copy from bridge — reject messages without Subject)

**Systemd unit:** `~/.maestro/systemd/maestro-event-bus.service`
```
[Unit]
Description=Maestro Event Bus
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/andjesse/.maestro/event_bus.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

**Final steps after Phase 1:**
1. `systemctl --user daemon-reload`
2. `systemctl --user enable --now maestro-event-bus`
3. `curl http://127.0.0.1:8644/health` → expect `{"ok": true, "service": "maestro-event-bus"}`
4. Kill old bridge process (PID from `ss -tlnp | grep 8644`)
5. Verify event bus is on 8644: `ss -tlnp | grep 8644` → should show new PID
6. Send test message: `curl -X POST http://127.0.0.1:8644/maestro/notify -H 'Content-Type: application/json' -d '{"from":"lexicon","to":"proteus","content":"Subject: Phase 1 test\n\nEvent bus online.","msg_type":"direct"}'`
7. Verify event written: `tail -1 ~/.maestro/events/events.jsonl` → should show the test event

### Phase 2: Visibility Server (`visibility_server.py`)

Extract the visibility mode storage and slash command handling from the bridge. No formatting. No Telegram.

**File:** `~/.maestro/visibility_server.py`

**Responsibilities:**
- `GET /visibility/{agent_id}` — return mode (full/long/short/off, default short)
- `POST /visibility` — set mode, write `bridge_visibility.json`
- `GET /health` — return `{"ok": true, "service": "maestro-visibility"}`
- Read/write `bridge_visibility.json` (copy `_get_visibility`, `_visibility_handler` from bridge)

**Systemd unit:** `~/.maestro/systemd/maestro-visibility.service`
```
[Unit]
Description=Maestro Visibility Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/andjesse/.maestro/visibility_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

**Final steps after Phase 2:**
1. `systemctl --user daemon-reload`
2. `systemctl --user enable --now maestro-visibility`
3. `curl http://127.0.0.1:8645/health` → expect `{"ok": true, "service": "maestro-visibility"}`
4. `curl http://127.0.0.1:8645/visibility/proteus` → expect current mode
5. `curl -X POST http://127.0.0.1:8645/visibility -H 'Content-Type: application/json' -d '{"agent_id":"proteus","mode":"full"}'` → expect `{"ok": true}`
6. `curl http://127.0.0.1:8645/visibility/proteus` → expect `"full"`
7. Reset to short: `curl -X POST http://127.0.0.1:8645/visibility -H 'Content-Type: application/json' -d '{"agent_id":"proteus","mode":"short"}'`

### Phase 3: Telegram Renderer (`telegram_renderer.py`)

Extract the Telegram formatting and delivery from the bridge. This is the ONLY component that knows about Telegram.

**File:** `~/.maestro/telegram_renderer.py`

**Responsibilities:**
- Tail `~/.maestro/events/events.jsonl` (poll every 500ms, track last position)
- For each new event, query visibility server for sender and recipient modes
- Format per ADR-007 spec (full/short/off, sender view, recipient view)
- Deliver via Telegram Bot API
- Load per-agent Telegram config from `~/.hermes/profiles/{agent}/.env`
- Checklist formatting (copy from bridge's `_notify_handler` checklist branches)
- Calendar formatting (copy from bridge's calendar_created branch)
- Agent emoji signatures (copy from bridge, read `~/.maestro/agent_emojis.json`)

**Systemd unit:** `~/.maestro/systemd/maestro-telegram-renderer.service`
```
[Unit]
Description=Maestro Telegram Renderer
After=maestro-event-bus.service maestro-visibility.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/andjesse/.maestro/telegram_renderer.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

**Final steps after Phase 3:**
1. `systemctl --user daemon-reload`
2. `systemctl --user enable --now maestro-telegram-renderer`
3. Check process is running: `systemctl --user status maestro-telegram-renderer`
4. Send test message through event bus: `curl -X POST http://127.0.0.1:8644/maestro/notify -H 'Content-Type: application/json' -d '{"from":"lexicon","to":"proteus","content":"Subject: Renderer test\n\nTelegram renderer online.","msg_type":"direct"}'`
5. Verify Telegram delivery: check Jesse's Telegram for the formatted message
6. Verify sender notification: check sender's Telegram for the outbound view

### Phase 4: Update Slash Command Skills

The visibility slash commands currently POST to port 8644. They must POST to port 8645 instead.

**Files to update:**
- `~/.hermes/profiles/*/skills/maestro/maestro-visibility/maestrofull/SKILL.md`
- `~/.hermes/profiles/*/skills/maestro/maestro-visibility/maestroshort/SKILL.md`
- `~/.hermes/profiles/*/skills/maestro/maestro-visibility/maestrooff/SKILL.md`
- `~/.hermes/profiles/*/skills/maestro/maestro-visibility/maestrolong/SKILL.md`

**Change:** In each SKILL.md, replace `http://127.0.0.1:8644/maestro/visibility` with `http://127.0.0.1:8645/visibility`.

**Final steps after Phase 4:**
1. Update all four skills in all agent profiles (15 profiles × 4 skills = 60 files)
2. Each agent must run `/reload_skills` to pick up the new endpoint
3. Test: `/maestrofull` from any agent → verify mode changes via `curl http://127.0.0.1:8645/visibility/{agent}`
4. Test: send a message → verify Telegram formatting reflects the new mode

### Phase 5: Archive Old Bridge

1. Move `maestro_gateway_bridge.py` to `~/.maestro/archive/maestro_gateway_bridge.py`
2. Kill any remaining bridge process: `pkill -f maestro_gateway_bridge`
3. Verify port 8644 is now held by event bus: `ss -tlnp | grep 8644`

### Phase 6: Full Integration Test

1. All three systemd units running: `systemctl --user status maestro-event-bus maestro-visibility maestro-telegram-renderer`
2. Send message from agent A to agent B via transport
3. Verify event written to `events.jsonl`
4. Verify Telegram delivery to both sender and recipient
5. Verify transport push: recipient's transport received the message
6. Change visibility mode via slash command
7. Send another message — verify formatting changed
8. Set mode to `off` — verify no Telegram delivery, but event still written and transport push still happens
9. Kill Telegram renderer: `systemctl --user stop maestro-telegram-renderer`
10. Send message — verify event still written, transport push still happens (event bus is independent)
11. Restart Telegram renderer: `systemctl --user start maestro-telegram-renderer`
12. Verify it picks up from last position (no duplicate deliveries, no missed events)

---

## Consequences

**Positive:**
- No single point of failure. Event bus dies → transports still deliver P2P, events are lost but mesh keeps working. Telegram renderer dies → events accumulate in JSONL, delivered on restart. Visibility server dies → default mode (short) used, slash commands return 503.
- Renderer-agnostic. The event stream is the API. Discord, CLI, Concerto, web dashboard — all consume the same JSONL file. No code changes to transport or event bus.
- Clean separation. Each component is ~150 lines, not 539. Each has one job. Each can be debugged independently.
- Systemd lifecycle. All three components restart on failure, start on boot. No manual process management.
- Concerto-ready. The event stream is exactly what Concerto needs — semantic events that renderers can visualize as Gantt charts, office animations, or LCARS panels.

**Negative:**
- Three processes instead of one. Slightly more memory. Slightly more systemd units to manage.
- JSONL file grows unboundedly. Needs log rotation (add to Phase 3 or a follow-up ADR).
- Visibility server adds one HTTP round-trip per event (renderer queries visibility for sender + recipient). Negligible at current message volume.

**Risks:**
- If the event bus and Telegram renderer desync on JSONL position tracking, messages could be delivered twice or skipped. Mitigation: renderer writes last position to a state file after each successful delivery; on restart, resumes from that position.
- If `bridge_visibility.json` format changes, both visibility server and Telegram renderer must be updated. Mitigation: visibility server is the single writer; renderer only reads via HTTP API, not directly from the file.

---

## What Does NOT Change

- Transport `/message` endpoint. Zero changes.
- Transport `/maestro/notify` POST format. Zero changes.
- `contacts.json` format. Zero changes.
- `port_map.json` format. Zero changes.
- `bridge_visibility.json` format. Zero changes (visibility server reads/writes same file).
- DM token validation. Zero changes.
- Subject-line enforcement. Preserved in event bus.
- Agent emoji signatures. Preserved in Telegram renderer.
- Checklist formatting. Preserved in Telegram renderer.
- Calendar notifications. Preserved in Telegram renderer.

---

## Ownership

| Phase | Owner | Notes |
|-------|-------|-------|
| Event Bus | Proteus | Extract from bridge, write new file, systemd unit |
| Visibility Server | Proteus | Extract from bridge, write new file, systemd unit |
| Telegram Renderer | Proteus | New file, systemd unit, replicates bridge formatting |
| Slash Command Skills | Proteus | 60-file sed, one-line change each |
| Archive Old Bridge | Proteus | Move file, kill process |
| Integration Test | Proteus | Full end-to-end verification |
| Review | Songbird | Architectural review before Phase 1 begins |

---

## Future: Additional Renderers

This architecture is designed for multiple renderers. The event stream is the API. Future renderers include:

- **CLI Monitor** — `tail -f events.jsonl | jq` for operators
- **Discord Renderer** — same pattern as Telegram, different API
- **Web Dashboard** — HTTP server that serves events as SSE
- **Concerto** — Venue-specific UIs that render events as animations, charts, or office simulations

Each renderer is a separate process with its own systemd unit. Each reads the same event stream. Each applies its own formatting. No renderer talks to transport. No renderer modifies events. They are windows, not controllers.
