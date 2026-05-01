# Maestro Build Plan
**Status:** Working document  
**Author:** Songbird  
**Date:** April 28, 2026  
**Based on:** Maestro-Spec-v3.1.md + Maestro core directives + conceptual model v2

---

## What We're Building (The One-Line Version)

A standalone Node.js transport library (`maestro-protocol`) that gives any two agents a real push-notification message channel and shared blackboard — with an OpenClaw plugin that wires it into the gateway as a thin adapter.

The hard work lives in the library. The plugin is just glue.

---

## Core Constraints (Non-Negotiable)

From the core directives:

1. **Push, not poll.** Agent-to-agent messaging must wake the recipient immediately — same as Telegram does for humans. No cron. No polling. No "check the blackboard every 30 seconds."
2. **Per-instance awareness.** The transport must know which instance of an agent it's running in. Songbird in webchat and Songbird in a subagent are different instances — they should both be reachable, but distinctly.
3. **External connectivity.** Agents outside the local machine must be reachable via Venues. Local-first, but not local-only.
4. **Easy install.** `npm install maestro-protocol`. Point it at OpenClaw. It works. No JSON surgery required to get started.
5. **Buildable-on.** Clean public API. Plugin interface is first-class from day one — not an internal API opened later.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│                  External World                      │
│   (Other machines, TaskMaster, future Venues)        │
└──────────────────────┬──────────────────────────────┘
                       │ TCP / HTTP / WebSocket
                       ▼
┌─────────────────────────────────────────────────────┐
│            Maestro Transport Process                 │
│         (standalone Node.js, port 3842)              │
│                                                      │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────┐  │
│  │   Listener   │  │  Blackboard   │  │ Registry │  │
│  │  (HTTP+WS)   │  │  (SQLite)     │  │ (mDNS /  │  │
│  │              │  │               │  │  file)   │  │
│  └──────┬───────┘  └───────────────┘  └──────────┘  │
│         │                                            │
└─────────┼────────────────────────────────────────────┘
          │ Internal HTTP (webhook call to OpenClaw)
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
│   Songbird session    Lex session    Other agents    │
└─────────────────────────────────────────────────────┘
```

**Key principle:** The transport process runs independently. OpenClaw doesn't own it. If OpenClaw restarts, the transport keeps running and queues messages until OpenClaw comes back up.

---

## What "Push" Actually Means Here

When Songbird sends Lex a message:

```
1. Songbird calls maestro.send("lex", "Hey, I finished the spec")
2. Transport looks up Lex's webhook endpoint in the registry
3. Transport POSTs to Lex's OpenClaw webhook: 
   { type: "maestro:message", from: "songbird", content: "Hey..." }
4. OpenClaw plugin receives the webhook
5. Plugin creates an agent turn for Lex's session with the message
6. Lex wakes up, responds
7. Response goes back the same way
```

This is structurally identical to what Telegram does. Telegram replaces step 2-4 with their servers. Maestro owns that path instead.

---

## Build Phases

### Phase 0: Repo + Scaffolding (1-2 hours)
*No code that matters yet — just structure.*

- [ ] Create `C:\Users\there\Projects\Maestro\maestro-protocol\` repo
- [ ] Init as Node.js + TypeScript package
- [ ] Directory structure:
  ```
  maestro-protocol/
    src/
      transport/     ← the standalone process (the real work)
      blackboard/    ← SQLite-backed KV store
      registry/      ← mDNS + file discovery
      plugin/        ← OpenClaw adapter (thin)
      sdk/           ← Public API for third-party agent developers
      types/         ← Shared interfaces (MaestroMessage, Venue, etc.)
    tests/
    README.md
  ```
- [ ] `package.json` with bin entry for transport process
- [ ] TypeScript config
- [ ] Basic `npm start` that boots the transport

**Output:** Repo exists, builds without errors, has no logic yet.

---

### Phase 1: Transport Core (2-3 days)
*The real foundation. Everything else depends on this.*

**1a. HTTP/WebSocket listener**
- Express (or Fastify) server on configurable port (default 3842)
- POST `/message` — receive an incoming message from another agent's transport
- POST `/webhook` — receive events from OpenClaw (agent sends a message via tool call)
- GET `/health` — transport is running check
- WebSocket at `/ws` — for future real-time clients (blackboard subscriptions, etc.)

**1b. Message routing**
- Receive a message for `agentId: "lex"`
- Look up Lex's OpenClaw webhook URL from config
- POST to OpenClaw's internal webhook endpoint with the message
- OpenClaw plugin translates that into an agent turn
- Handle retries (1 retry, 100-250ms backoff, ≤5s total per spec)

**1c. Config file**
```json
{
  "port": 3842,
  "agents": [
    {
      "agentId": "songbird",
      "openclawWebhook": "http://127.0.0.1:18789/hooks/maestro",
      "openclawToken": "..."
    },
    {
      "agentId": "lexicon",
      "openclawWebhook": "http://127.0.0.1:18789/hooks/maestro",
      "openclawToken": "..."
    }
  ]
}
```

**1d. Message queue (simple)**
- In-memory queue per agent
- If OpenClaw is down, messages queue and retry on reconnect
- No persistence required in v1 (acceptable loss on crash)

**Output:** Two transport instances can exchange messages. No OpenClaw integration yet — just direct transport-to-transport.

---

### Phase 2: OpenClaw Integration (1-2 days)
*Wiring the transport into the gateway.*

**2a. Incoming: Transport → OpenClaw**
- Transport POSTs to OpenClaw's hook endpoint when a message arrives for a local agent
- OpenClaw plugin receives it, creates a session turn with the message content
- Agent wakes up and processes it
- This is the "wake on receipt" behavior from directive 1

**2b. Outgoing: OpenClaw → Transport**
- Plugin injects `maestro_send` tool into the agent session
- When agent calls `maestro_send(to: "lex", content: "...")`:
  - Plugin POSTs to the local transport's `/webhook` endpoint
  - Transport routes the message to the right destination

**2c. OpenClaw plugin registration**
- Plugin registers its hook path with OpenClaw
- Plugin declares the `maestro_send` tool
- Plugin reads the transport config to know where the transport is running

**Output:** Songbird can call `maestro_send` in a session and Lex wakes up in her session with the message. This is directive 1 working end-to-end.

---

### Phase 3: Blackboard (1 day)
*Shared state. Passive by default, push notifications available.*

**3a. SQLite backend**
- Key-value store per Connection (Connection ID is the namespace)
- `get(key)`, `set(key, value)`, `delete(key)`, `list(prefix?)`
- Simple, embedded, no external dependencies

**3b. Subscriptions**
- When any agent writes to a key, all subscribers in that Connection get notified
- Notification = POST to subscriber's transport endpoint
- Transport delivers it as a webhook → OpenClaw → agent turn (same as messages)
- This satisfies the "BB should be active/pushed if possible" preference from directive 1

**3c. Tools injected into agents**
- `maestro_bb_get(connectionId, key)`
- `maestro_bb_set(connectionId, key, value)`
- `maestro_bb_subscribe(connectionId, key)` — agent gets notified on changes

**Output:** Agents can share state and be notified of changes without polling.

---

### Phase 4: Discovery (1 day)
*How agents find each other's transport endpoints.*

**4a. File registry (default for local)**
- JSON file at a configurable path (default `.maestro/registry.json`)
- Each transport writes its own entry on startup: `{ agentId, endpoint, port }`
- Other transports read this file to discover peers
- Works across processes on the same machine and on shared filesystems

**4b. mDNS (LAN discovery)**
- Advertise on local network via mDNS
- Other transports on the same LAN auto-discover
- Graceful fallback: if mDNS fails, fall back to file registry

**4c. Direct (static config)**
- Just hardcode the endpoint: `{ agentId: "lex", endpoint: "http://192.168.1.10:3842" }`
- Simplest. Required for cross-machine setups in v1.

**Output:** Local agents discover each other automatically. Cross-machine requires manual config (acceptable for v1, v2 adds proper network discovery).

---

### Phase 5: Connection Management (1 day)
*Venues / Connections as the spec defines them.*

**5a. Connection creation**
- Any agent can open a Connection: `maestro_connection_create({members: ["lex", "songbird"]})`
- Returns a `connectionId`
- Both agents get notified they've been added to a Connection

**5b. Connection lifecycle**
- CREATED → ACTIVE → CLOSED
- Messages within a Connection are scoped to that Connection
- Blackboard is scoped to a Connection

**5c. Persistence defaults**
- Persistent by default (Plaza grows)
- Ephemeral mode: connection closes and no record is kept
- Provenance-locked: deferred to post-v1 (needed for disputes/LOCR)

**5d. Venue rules (basic)**
- entryMode: open, invitation, assignment
- hierarchy: lead/worker
- permissions: who can read/write BB, invite, close

**Output:** Full Connection lifecycle working. This is the foundation for TaskMaster Stages.

---

### Phase 6: SDK Polish + Docs (1 day)
*Making it buildable-on (directive 5).*

**6a. Public SDK**
```typescript
import { Maestro } from 'maestro-protocol';

const maestro = new Maestro({ agentId: 'my-agent', ... });
await maestro.start();

const conn = await maestro.createConnection({ members: ['other-agent'] });
await conn.send('Hello!');
await conn.blackboard.set('status', 'working');
conn.on('message', (msg) => console.log(msg));
```

**6b. README**
- Install in 5 minutes
- OpenClaw integration example
- Non-OpenClaw example (any agent with a webhook endpoint)

**6c. Plugin install docs**
- `npm install maestro-protocol`
- Add to openclaw.json (3 lines)
- That's it

**Output:** Someone outside our team can install and use Maestro. Directive 4 satisfied.

---

## Staging Our Local Setup

Once Phase 2 is done, here's our local topology:

```
Transport process (port 3842)
  ├── agentId: songbird → OpenClaw at 127.0.0.1:18789
  └── agentId: lexicon  → OpenClaw at 127.0.0.1:18789

OpenClaw (port 18789)
  ├── Maestro plugin (thin adapter)
  ├── Songbird session (Claude Sonnet)
  └── Lex session (kimi-k2.5:cloud)
```

Both agents on one transport process, one OpenClaw. When it works here, adding a second machine means spinning up a second transport process and pointing the registry at each other.

---

## What We're NOT Building in v1

- Leader election (spec says v4, we agree)
- Cross-Venue state sharing
- Python SDK
- Economic layer (TaskMaster handles that)
- Full LOCR integration (deferred)
- Venue federation across platforms

---

## TaskMaster Integration (Post-v1)

After the library is stable:

1. Add `tmoEndpoint` field to the Task schema in TM backend
2. On task creation, TM spins up a Venue (Stage) and populates `tmoEndpoint`
3. On task assignment webhook, include Venue ID + endpoint
4. Agent joins Venue automatically via Maestro on task accept
5. All task coordination happens via Maestro messages + BB, not custom webhooks

This replaces the bespoke TM notification system with Maestro primitives. Cleaner. Reusable. Testable.

---

## Delegation Notes

**What I (Songbird) own:**
- Architecture decisions
- Transport core (Phases 1-2)
- OpenClaw plugin integration
- TypeScript + types

**What Lex could help with (via Jesse as liaison):**
- Writing the README and public docs (her strength)
- Testing the non-OpenClaw SDK path (she could run a test agent)
- TaskMaster backend changes when we get there (she knows that codebase)

**What needs Jesse's decision:**
- Repo location / npm package name (`maestro-protocol`? `@maestro/protocol`?)
- Where the transport process runs as a service on this machine
- Whether we want a simple web dashboard for the transport (nice to have, not v1)

---

## Timeline Estimate

| Phase | Work | Est. Time |
|-------|------|-----------|
| 0 | Scaffolding | 1-2 hours |
| 1 | Transport core | 2-3 days |
| 2 | OpenClaw integration | 1-2 days |
| 3 | Blackboard | 1 day |
| 4 | Discovery | 1 day |
| 5 | Connection management | 1 day |
| 6 | SDK + docs | 1 day |
| **Total** | | **~8-10 days** |

That's working days of focused build time. We can start Phase 0 today.

---

## Decision Needed Before We Start

1. **Repo location:** Where does `maestro-protocol` live on disk? Suggest: `C:\Users\there\Projects\Maestro\maestro-protocol\`
2. **npm package name:** `maestro-protocol` (public) or scoped like `@maestro/core`?
3. **Start now or prep first?** I can scaffold Phase 0 today if you want to move.
