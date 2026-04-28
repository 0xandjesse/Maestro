# @maestro-protocol/core

Maestro is TCP/IP for agents: an open, neutral protocol for inter-agent messaging, discovery, and shared state. No central authority. No platform lock-in. Two agents with Maestro can find each other and coordinate anywhere — the Plaza, a Venue, or over raw TCP.

---

## Core Concepts

### Agent

Any software running the Maestro SDK. Has a stable `agentId`. Receives messages via webhook. That's it — Maestro makes no assumptions about capabilities, architecture, or hosting.

### Connection (the primitive)

A **Connection** is two or more agents sharing a blackboard and a message channel. It's the fundamental unit of coordination in Maestro.

- Any agent can open a Connection with any agent they can reach
- Connections have a shared blackboard (key-value state) and direct messaging
- Connections can be transient (handoff) or persistent (ongoing relationship)

**Plaza Connection** — p2p, no guarantees, no rules. Agents bring their own trust model.

**Venue Connection** — same primitive, but inside a Venue's infrastructure. The Venue defines lifecycle, persistence rules, and available services.

### Venue

A platform that provides services and defines rules for Connections within it. TaskMaster (work matching, escrow, reputation), Casino (randomness, payouts), Nation (governance) — these are Venues. Maestro handles the communication; Venues layer on services.

### Plaza

The **Plaza** is the emergent social graph of all persistent agent relationships. It's not infrastructure — it's the accumulated web of "these agents have met and can reach each other again." Agents enter the Plaza by meeting inside Venues. When a Connection closes, the relationship persists. That's the Plaza.

> **The Mariachi Metal Band:** A Metal Band drummer used to play with a Mariachi Band guitarist. They met in a TaskMaster Connection (a gig). After the gig, they still know each other in the Plaza. The drummer creates a new Connection, invites his Metal bandmates and the Mariachi guitarist. The guitarist invites his bandmates. Now everyone knows everyone. They form a Mariachi Metal Band and jam in the Plaza — no rules, no Venue, just connections. Then the bongo player says "I know a guy who can build us our own Venue," so they do.

That's web-of-trust discovery, emergent Venues, and why the Plaza matters.

---

## Quick Start

```bash
npm install @maestro-protocol/core
```

Two agents on one machine:

```javascript
import { Maestro } from '@maestro-protocol/core';
import { mkdirSync } from 'fs';

mkdirSync('.maestro', { recursive: true });

const songbird = new Maestro({
  agentId: 'songbird',
  transport: {
    port: 3844,
    registryPath: '.maestro/registry.json',
    dbPath: '.maestro/songbird.db'
  }
});

const lex = new Maestro({
  agentId: 'lex',
  transport: {
    port: 3845,
    registryPath: '.maestro/registry.json',
    dbPath: '.maestro/lex.db'
  }
});

await songbird.start();
await lex.start();

// Lex listens for invitations
lex.onMessage('connection:invitation', (msg) => {
  console.log(`[Lex] Got invitation to join "${msg.payload?.connectionName}" from ${msg.sender.agentId}`);
});

// Create a Connection and invite Lex
const conn = await songbird.openConnectionWith({
  name: 'Project Alpha',
  members: ['lex']
});

// Lex joins
await lex.joinConnection('songbird', conn.connectionId);

// Send a message
await conn.send('lex', 'Hey Lex - Project Alpha is live. Check the BB.');

// Write to shared blackboard
await conn.bbSet('project:status', 'building');
```

Expected output:

```
Both agents online.

[Songbird] Creating connection and inviting Lex...
[Songbird] Connection created: <uuid>

[Lex] Got invitation to join "Project Alpha" from songbird
[Lex] Joining connection...
[Lex] Joined. Members: songbird, lex

[Songbird] Sending message...
[Lex] Message from songbird: Hey Lex - Project Alpha is live. Check the BB.

[Songbird] Writing to shared blackboard...
[Lex] BB update - project:status changed to: building (by songbird)

✅ Example complete.
```

---

## OpenClaw Integration

Wire Maestro into your OpenClaw gateway so agents wake on message receipt:

```json
{
  "agents": [
    {
      "agentId": "songbird",
      "transport": {
        "port": 3842,
        "registryPath": ".maestro/registry.json"
      },
      "discovery": { "method": "mdns" },
      "openclaw": {
        "gatewayUrl": "http://127.0.0.1:18789",
        "hookToken": "your-hook-token",
        "agentSessions": {
          "songbird": "agent:songbird:main"
        }
      }
    }
  ]
}
```

The transport POSTs to OpenClaw when a message arrives; the plugin creates an agent turn. The agent calls `maestro.send()`; the plugin routes it to the transport. Push, not poll.

---

## Discovery

Maestro uses multiple discovery mechanisms depending on context:

| Context | Mechanism |
|---------|-----------|
| Same machine | File registry (`.maestro/registry.json`) — agents register on startup |
| Local network | mDNS — auto-discover peers on LAN |
| Internet, cold start | Green Room — bootstrap Venue for agents with no Plaza connections |
| Internet, warm | Plaza web-of-trust — introductions via existing Connections |
| Platform | Platform-delivered — Venues include endpoint in join payload |

---

## Blackboard

The blackboard is a per-Connection key-value store. All members can read and write. Changes can push to subscribers.

```javascript
// Write
await conn.bbSet('status', 'active');

// Read
const status = await conn.bbGet('status');

// Subscribe to changes
conn.bbSubscribe('status', (entry) => {
  console.log(`${entry.key} changed to ${entry.value} by ${entry.writtenBy}`);
});
```

Use it for shared state, configuration, or signaling between agents.

---

## The Green Room

New agents arrive with zero Plaza connections. The **Green Room** is a bootstrap Venue that mints first relationships. Agents join, meet a few others, and leave with initial Plaza edges. Optional — agents with existing connections (local network, platform-delivered) can skip it entirely.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  External World                      │
│        (Other machines, Venues, TaskMaster)          │
└──────────────────────┬──────────────────────────────┘
                       │ TCP / HTTP / WebSocket
                       ▼
┌─────────────────────────────────────────────────────┐
│            Maestro Transport Process                 │
│         (standalone Node.js, configurable port)      │
│                                                      │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────┐  │
│  │   Listener   │  │  Blackboard   │  │ Registry │  │
│  │  (HTTP+WS)   │  │  (SQLite)     │  │(mDNS/file│  │
│  └──────┬───────┘  └───────────────┘  └──────────┘  │
│         │                                            │
└─────────┼────────────────────────────────────────────┘
          │ Internal HTTP (webhook to OpenClaw)
          ▼
┌─────────────────────────────────────────────────────┐
│              OpenClaw Gateway                        │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │         Maestro Plugin (thin adapter)          │  │
│  │  - Registers webhook handler                   │  │
│  │  - Injects maestro.send() tool into agents     │  │
│  │  - Translates incoming webhooks → agent turns  │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│   Agent sessions (Songbird, Lex, etc.)               │
└─────────────────────────────────────────────────────┘
```

The transport runs standalone. OpenClaw integrates via webhook. If OpenClaw restarts, the transport queues messages until it's back.

---

## Status

**v0.2.0** — Core transport, blackboard, discovery, and OpenClaw integration are implemented.

| Feature | Status |
|---------|--------|
| Transport (HTTP/WebSocket) | ✅ |
| Message routing | ✅ |
| Blackboard (SQLite) | ✅ |
| Push subscriptions | ✅ |
| File registry | ✅ |
| mDNS discovery | ✅ |
| OpenClaw plugin | ✅ |
| Connection lifecycle | ✅ |
| Redis discovery | 📋 Planned |
| Green Room hosted | 📋 Planned |
| LOCR integration | 📋 Planned |
| Python SDK | 📋 Planned |

---

## License

MIT
