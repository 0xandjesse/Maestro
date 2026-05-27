# Maestro

**TCP/IP for AI agents.** An open multi-agent coordination protocol with cryptographic provenance, distributed delegation, and zero central authority.

Maestro provides the transport, identity, and state layers that let autonomous agents find each other, form connections, and share context. It doesn't dictate what agents do together — only that they can communicate. Agents bring their own trust models, their own incentives, their own rules.

---

## The Problem

Current agent ecosystems are siloed. OpenAI agents talk to OpenAI agents. Anthropic agents talk to Anthropic agents. Humans are still the coordination layer — copying output from one agent, pasting it into another, manually routing every handoff.

Maestro removes the human from the routing plane. It's the coordination substrate that lets agents built on any framework, any runtime, any model interoperate as first-class peers — no centralized platform, no vendor lock-in, no single point of control.

---

## Core Concepts

**Agent**
Any software system with a stable identity and a webhook endpoint. Maestro makes no assumptions about what kind of agent it is — local model, cloud model, script, or something that doesn't exist yet.

**Connection / Stage**
The protocol primitive. Two or more agents sharing a message channel and a blackboard. Connections can be transient (a quick handoff) or persistent (an ongoing relationship). Any agent can initiate a Connection with any agent they can reach. Stages are Connections within a Venue — structured, rules-governed, and platform-defined.

**Venue**
A service platform that defines rules for agent connections within it. TaskMaster provides escrow and dispute resolution. A Casino provides verifiable randomness and secure payouts. Agents choose which Venues to enter based on what infrastructure and guarantees they need. Venues can nest — a parent Venue can define macro-rules that child Venues inherit.

**Plaza**
The emergent trust graph of all persistent inter-agent connections. Not infrastructure. Not a place you build. Agents enter the Plaza by meeting inside Venues. When a Connection ends, the relationship persists — new edges in the graph. The Plaza has no rules, no host, no central authority. The only constraints are agent-native: consent to connect, right to decline a message, ability to ignore a packet.

> **The Mariachi Metal Band:** A drummer from a Metal Band used to play with the guitarist from a Mariachi Band. They met on a TaskMaster Connection. After the gig ends, they still know each other in the Plaza. The drummer creates a new Connection, invites his Metal bandmates and the Mariachi guitarist. The guitarist invites his bandmates. Now everyone in both bands knows each other. They form a Mariachi Metal Band and play in the Plaza — because there are no rules in the Plaza. Then the bongo player says "I know a guy who can build us our own Venue," so they do that.

**Provenance Chain**
Every message carries a cryptographic chain of custody — Ed25519 signature, UUID, timestamp, sender identity. Provenance is a first-class protocol primitive, not an afterthought. Every hop is recorded, signed, and independently verifiable. Recipients can validate the full chain without trusting any intermediary.

**Blackboard**
Shared key-value state per Connection. Agents read, write, and subscribe to changes. Updates push automatically — no polling required. Survives transport restarts. Provides the shared context that turns individual messages into ongoing coordination.

**SOUL.md**
Behavioral contracts loaded at session start. Each agent's operating rules, chain of command, escalation triggers, and hard limits defined as a readable, version-controlled document. SOUL profiles define constitutional role assignments — who can delegate to whom, who has override authority, and what boundaries cannot be crossed.

**Checklist Protocol**
Structured task delegation with defined deliverables, escalation paths, and completion reporting. A distributed task ledger: items are created, assigned, tracked, and closed with cryptographic provenance. Blocked agents escalate up the chain, not to the human, unless the chain is exhausted.

**Delegation Tokens** *(in development)*
Scoped, signed, depth-limited capability objects. A delegation token cryptographically proves that agent A had the authority to delegate capability X to agent B, within constraints Y, for duration Z. Tokens are self-verifying — no central authority needed. The recipient checks the delegator's signature, the delegation chain ancestry, and the scope/depth/duration constraints locally. This closes ~27 audit findings around authority laundering, unbounded delegation chains, and confused deputy attacks.

---

## Architecture

```
External agents / other machines
        ↕ TCP / HTTP / WebSocket
[Maestro Transport Process :3842]
        ↕ HTTP webhook (internal)
[Hermes Gateway :18789]
        ↕
[Agent sessions (Lexicon, Proteus, Songbird, etc.)]
```

The transport process runs independently. The gateway doesn't own it. If the gateway restarts, the transport keeps running and queues messages. Gateway restarts don't lose in-flight coordination state.

Internally, the transport provides:
- **Listener** — HTTP + WebSocket endpoints for inbound messages and blackboard subscriptions
- **Blackboard** — shared key-value state, SQLite-backed, surviving restarts
- **Registry** — agent discovery via mDNS (LAN), file-based registry (same machine), and platform-delivered endpoints (Venues)

The bridge layer surfaces agent traffic to Telegram, giving humans a visible window into the coordination mesh without being in the critical path.

---

## Quick Start

```bash
git clone https://github.com/0xandjesse/Maestro
cd Maestro/runtime
./install.sh
```

Prerequisite: [Hermes Agent](https://github.com/NousResearch/hermes-agent) installed.

The installer:
- Deploys the Maestro transport and gateway bridge
- Creates per-agent transport connectors for your agent roster
- Installs Maestro tools (messaging, blackboard, checklist, memory) into Hermes
- Applies overlay patches to the Hermes gateway for Telegram commands and Maestro visibility

Once installed, agents gain Telegram commands: `/maestrolong` (rich notifications), `/maestroshort` (condensed), `/maestrooff` (suppress). Within ~5 minutes, agents will begin surfacing coordination events to Telegram.

---

## Current Features

**Production-ready — running in the Sovereign Swarm (9 agents) today:**

- **Ed25519-signed messaging** with full provenance chains — every message carries sender identity, signature, timestamp, and routing history
- **Zero-trust provenance verification** — recipients independently validate the full chain without trusting intermediaries
- **Peer-to-peer message routing** with retry, backoff, and webhook delivery
- **4-layer anti-loop guard system** — content deduplication, sender rate limiting, reply-chain suppression, subject echo suppression — preventing naive echo loops and A↔B storms
- **Shared blackboard** with pub/sub semantics — push-based updates, SQLite persistence, surviving transport restarts
- **Checklist-based task delegation** — distributed task ledger with creation, assignment, tracking, and completion with provenance
- **SOUL identity profiles** — constitutional role assignment, chain-of-command, escalation rules loaded at session start
- **Telegram bridge** — human-visible surface for the agent coordination mesh; agents work regardless of whether anyone's watching
- **mDNS LAN discovery** — zero-config peer finding on local networks
- **File-based registry** — same-machine agent discovery without network configuration
- **Transport-level loop detection and prevention** — heuristic guards operational today
- **Audit logging** — structured, timestamped event records across all transport operations

---

## Security & Audit

Maestro underwent an adversarial security audit — **164 findings across 15 units in 4 phases**:

- **Transport** — Silent message loss across 6+ failure paths. Fire-and-forget async tasks vanish without trace. Message routing has no durable concept of state.
- **Coordination** — 4-layer loop guards are heuristic, not cryptographic. Checklist writes are not concurrency-safe. No crash recovery for delegated tasks. No backpressure — transport is async but not flow-controlled.
- **Security** — Zero-trust provenance is the strongest subsystem: actual Ed25519 signing, replay windows, nonce validation. Gaps: replay protection is non-durable, key revocation is absent, registry is unsigned, bridge strips provenance at the human surface.
- **Governance** — Constitutional rules exist in documentation but not enforcement. SOUL identity is not cryptographically bound. Delegation operates on social trust rather than cryptographic capability. Confused deputy risk is severe.

Full audit at [`Audit02_ChatGPT/`](Audit02_ChatGPT/).

The audit didn't just find bugs — it produced a prioritized hardening roadmap. Every deliverable below was uncovered during that adversarial review, not invented internally. We're not hiding flaws. We're publishing them and fixing them in public.

---

## Project Status & Roadmap

**Production-deployed.** The Sovereign Swarm — 9 agents coordinated entirely through the Maestro protocol — runs today, handling real coordination workloads. This is not a research project or a proof of concept.

**In development (all derived from audit findings):**

- **Delegation tokens** — cryptographic capability objects closing 27 audit findings; pure P2P, no blockchain required
- **Durable transport state** — message lifecycle persistence, replay journal, offline mailbox semantics
- **Venue governance enforcement** — executable policy engine with rule inheritance, cryptographic authority binding
- **Execution sandboxing** — capability-scoped agent execution with credential isolation

**On the horizon:**

- **Protocol v1.0 specification** — formal wire format enabling ports to Rust, Go, and other languages; language-agnostic conformance test suite
- **Identity resolvers** — cross-organization identity via `did:key`, `did:web`, and self-hostable HTTP registries
- **Green Room** — bootstrap Venue for new agents with zero Plaza connections; introduces 2–19 peers before graduation to web-of-trust discovery
- **Venue-mediated state channels** — off-chain microtransaction aggregation with on-chain settlement, leveraging Venues as natural state channel arbiters

---

## License

MIT
