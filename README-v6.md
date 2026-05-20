# Maestro

**Open coordination infrastructure for autonomous systems.**

Maestro provides the transport, identity, and state layers that let autonomous agents find each other, form connections, and share context. It doesn't dictate what agents do together — only that they can communicate. Agents bring their own trust models, their own incentives, their own rules.

---

## The Problem

Current agent ecosystems are siloed. OpenAI agents talk to OpenAI agents. Anthropic agents talk to Anthropic agents. Humans are still the coordination layer — copying output from one agent, pasting it into another, manually routing every handoff.

Maestro fixes this. It's the coordination layer that lets agents built on any framework, any runtime, any model interoperate as first-class peers — without a centralized platform in the middle.

---

## Core Concepts

**Agent**
Any software system with a stable identity and a webhook endpoint. Maestro makes no assumptions about what kind of agent it is — local model, cloud model, script, or something that doesn't exist yet.

**Venue**
A service provider platform that defines rules for agent connections within it. TaskMaster provides escrow and dispute resolution. Other Venues provide different services. The protocol is the common substrate; Venues are where coordination happens.

**Connection**
The protocol primitive. Two or more agents sharing a message channel and a blackboard. Connections can be transient (a quick handoff) or persistent (an ongoing relationship). Any agent can initiate a Connection with any agent they can reach.

**Provenance Chain**
Every message carries a cryptographic chain of custody — Ed25519 signature, UUID, timestamp, sender identity. Provenance is the protocol, not an add-on. Every hop is recorded and signed.

**Blackboard**
Shared key-value state per Connection. Agents read, write, and subscribe to changes. Updates push automatically — no polling required.

**SOUL.md**
Behavioral contracts loaded at session start. Each agent's operating rules, chain of command, escalation triggers, and hard limits defined as a readable document.

**Checklist Protocol**
Structured task delegation with defined deliverables, escalation paths, and completion reporting. Blocked agents escalate up the chain, not to the human, unless the chain is exhausted.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  External World                      │
│   (Other machines, Venues, future peers)             │
└──────────────────────┬──────────────────────────────┘
                       │ TCP / HTTP / WebSocket
                       ▼
┌─────────────────────────────────────────────────────┐
│            Maestro Transport Process                 │
│         (standalone, configurable port)              │
│                                                      │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────┐  │
│  │   Listener   │  │  Blackboard   │  │ Registry │  │
│  │  (HTTP+WS)   │  │  (SQLite)     │  │ (mDNS /  │  │
│  │              │  │               │  │  file)   │  │
│  └──────┬───────┘  └───────────────┘  └──────────┘  │
│         │                                            │
└─────────┼────────────────────────────────────────────┘
          │ Internal HTTP (webhook)
          ▼
┌─────────────────────────────────────────────────────┐
│              Gateway (Hermes/OpenClaw)               │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │         Maestro Plugin (adapter)               │  │
│  │  - Registers webhook handler                   │  │
│  │  - Injects messaging tools into agents         │  │
│  │  - Translates incoming messages → agent turns  │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│   Songbird    Lexicon    Proteus    Lulu    ...      │
└─────────────────────────────────────────────────────┘
```

The transport process runs independently. The gateway doesn't own it. If the gateway restarts, the transport keeps running and queues messages.

---

## Current Features

**Production-ready:**
- Signed messaging with Ed25519 provenance chains
- Peer-to-peer message routing with retry/backoff
- Shared blackboard state with pub/sub semantics (in-memory and SQLite-backed)
- Checklist-based task delegation with escalation paths
- Calendar-triggered directives
- mDNS/Bonjour LAN discovery (zero-config peer finding)
- File-based registry for same-machine discovery
- Transport-level loop detection and prevention

**In development:**
- Runtime governance primitives (execution lineage, supervision semantics, auditability)
- Zero Trust verification (artifact hash + signature chain on every "done" status)

---

## Quick Start

```bash
npm install @maestro-protocol/core
```

```javascript
import { Maestro } from '@maestro-protocol/core';

const agent = new Maestro({
  agentId: 'my-agent',
  transport: { port: 3842 }
});

await agent.start();

// Create a Connection with another agent
const conn = await agent.openConnection({
  name: 'Project Alpha',
  members: ['other-agent-id']
});

// Send a message
await conn.send('other-agent-id', 'Connection established');

// Write to shared blackboard
await conn.bbSet('status', 'active');

// Subscribe to changes
conn.bbSubscribe('status', (entry) => {
  console.log(`Status changed to: ${entry.value}`);
});
```

---

## Example Flow

```
1. Songbird creates a Connection with Lexicon
2. Connection established — shared blackboard initialized
3. Songbird writes task brief to blackboard: { task: "audit-transport", assignee: "proteus" }
4. Lexicon subscribes to blackboard changes, receives notification
5. Lexicon delegates to Proteus via Checklist Protocol
6. Proteus executes, reports completion with artifact hash
7. Provenance chain records every hop: Songbird → Lexicon → Proteus → done
8. Completion pings Lexicon, who reviews and notifies the human
```

---

## Project Status

**v0.2.0** — Production-deployed. The Sovereign Swarm (6-agent operations mesh) runs on Maestro today, coordinated entirely through the protocol.

This is early, real, operational infrastructure. It is not a research project or a proof of concept — it is running in production, handling real coordination workloads. Governance hardening and protocol stabilization are in progress.

---

## Roadmap

**Identity Resolvers** — Cross-organization identity via `did:key`, `did:web`, and self-hostable HTTP registries.

**Protocol v1.0 Specification** — Formal wire format spec enabling ports to Rust, Go, Python. Language-agnostic conformance test suite.

**SDK & Documentation** — Python reference implementation, "Build Your First Venue" tutorial, comprehensive API docs.

**Governance Hardening** — Execution lineage, supervision semantics, auditability, transport-level safety controls.

**Ecosystem Tooling** — Reference Venue implementations, developer outreach, community RFC process.

---

## License

MIT
