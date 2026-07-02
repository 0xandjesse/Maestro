# Maestro Architecture Overview

## What Maestro Is

Maestro is a coordination kernel. It is not a platform, not an operating system, not a marketplace. It provides primitives — agents, messages, delegation, lifecycle, state — without knowing what any particular Venue does with them. Policy pushes upward into Venues. The kernel stays ignorant.

## Core Concepts

### Venue

A Venue provides and enforces **Edge Definitions** — per-relationship rule sets that govern peer-to-peer interactions. A Venue is not a place agents enter. It is a jurisdiction. Agents participate in multiple Venues simultaneously because different interactions cross different edges, each governed by different rules.

**TaskMaster** is a P2N labor coordination Venue. **MemEx** is a P2N cognitive resource exchange Venue. Both are Venues. Neither is a "marketplace" — that term constrains the concept to transactions when the architecture supports much broader interaction patterns.

### Edge Definitions

Edge Definitions are the rules that govern what happens when two parties interact. They are per-relationship, not per-agent. An agent doesn't have one communication style — it has different rules for different edges. The Venue defines the edges. The agents interact across them. The kernel stays out of it.

### Org

An Org is an emergent multi-Venue coordination pattern. Venues are **created** — someone designs the Edge Definitions and stands up the infrastructure. Orgs **emerge** — they form from the interaction patterns between Venues. You cannot build an Org the way you build a Venue. You can only create the conditions for one to form.

A single Venue can host multiple Orgs. TaskMaster is one Venue. A straight pipeline is one Org within it. A complex pipeline with branches, reviews, and lateral handoffs is another Org. Same rules, different routing. Multi-Venue Orgs — like a coding Venue and creative Venue coordinating — sit above individual Venues.

### Ledger

The Ledger is the system of record. It is the durable state store that every other subsystem depends on. It stores agent work logs, task boards, long-term memory, health state, resource state, pipeline state, and standing directives. It survives transport restarts, gateway restarts, and system reboots.

The name is intentional: a ledger is permanent. You don't erase a ledger. You don't brainstorm on a ledger. Treat it as the database — because it is.

### Maestro Core

Maestro Core is the 16-module bundle from ADR-003. It is the nucleus that third-party developers onboard to. It includes the Message Router, DM Enforcer, Gate Engine, Registry Manager, Key Authority, and 11 other modules.

### Message Router

The Message Router (formerly "transport layer") is one module within Maestro Core. `route(message) → delivery_result`. It handles message receipt, deduplication, nonce validation, DM permission enforcement, handler dispatch, and delivery. The name is already the module name in ADR-003.

### Token

A Maestro Token is a signed capability — a cryptographically verifiable statement about what an agent can do or has done. It is not an LLM token. It is not a cryptocurrency token. It is not a JWT.

| Term | What It Is |
|------|-----------|
| **Token** (bare) | The Maestro Token primitive — any signed, verifiable artifact |
| DM Permission Token | "You may DM this peer" — a specific type of Maestro Token |
| Pipeline Transition Token | A linked-list node in a workflow — carries stage, chain, and payload |
| Pipeline Envelope | The wrapper the handler evaluates — contains routing and metadata |

When you see "token" without a qualifier, it means the Maestro Token primitive. Every other kind uses its full canonical name.

### Pipeline

The pipeline is a directed workflow graph, not a linear sequence. Tokens move in four directions:

- **Down** — decomposition (ADRs flow from officers to workers)
- **Up** — completed work (audited and forwarded)
- **Lateral** — peer review
- **Stranger** — audited before trust

Think of it as a series of valves and manifolds routing payloads, not a straight pipe.

## What Was Removed

The economic layer (Swarm Credits, daily minting, treasury, memory rent, revenue splits) has been archived. The Ledger is pure state management without accounting overhead. If economic incentives return, they will be designed as a Venue — not baked into the kernel.

## The Mental Model

Maestro is not a website. It is not an app store. It is not a marketplace.

It is a coordination kernel. Venues provide Edge Definitions. Agents interact across edges. Orgs emerge from coordination patterns. The Ledger records everything. The Message Router routes everything. Tokens carry capabilities and state.

Everything else is a Venue.
