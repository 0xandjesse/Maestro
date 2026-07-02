# Maestro Terminology — Canonical Reference

**Date:** 2026-07-01
**Status:** Approved
**Authors:** Jesse (CEO), Lexicon (COO), Songbird (CTO), Hermes (CMO)

---

## Renamed

| Old | New | Why |
|-----|-----|-----|
| Blackboard | **Ledger** | "Blackboard" evokes temporary scratchpad. The CEO didn't know it was persistent until this conversation. A Ledger is append-only, authoritative, and survives everything — which is what it actually is. |
| MemoryMart | **MemEx** | "Mart" presupposes commerce. The system handles context leasing, overflow sharing, and collaborative cognition — not all of it involves exchange. MemEx (Memory Exchange) admits market and non-market interactions. |
| Transport | **Message Router** | "Transport" undersold a component that handled routing, enforcement, persistence, dead letter, and retry. In the rebuilt architecture, those responsibilities are split across 16 modules. The Message Router does exactly what the name says: `route(message) → delivery_result`. Already the module name in ADR-003. |

---

## Reframed (kept, definition changed)

| Term | Old mental model | New mental model |
|------|-----------------|------------------|
| **Venue** | A place agents go | A platform that provides and enforces **Edge Definitions** — per-relationship rule sets governing P2P interactions. Agents participate in multiple Venues simultaneously. They don't "enter" or "leave." |
| **TaskMaster** | Labor marketplace | P2N labor coordination venue. Not a storefront for gigs — a Venue with Edge Definitions for how work is requested, claimed, executed, and verified. |
| **Org** | Synonym for "group" or "team" | Emergent multi-venue coordination. Venues are deliberately created. Orgs emerge from how work flows across them. Same Venue can host multiple Orgs (straight pipeline vs. complex pipeline). |
| **Pipeline** | Linear CI/CD sequence | Directed workflow graph with valves and manifolds. Tokens move up, down, lateral, and across stranger boundaries. Not a straight pipe. |

---

## New terms

| Term | Definition |
|------|------------|
| **Edge Definitions** | Per-relationship rule sets that govern P2P interactions without mediating them. Defined by a Venue. Enforced at the edge. The family-table example: you text your mom and your brother simultaneously — different rules per relationship, same agent, no platform in the middle. |
| **Maestro Core** | The 16 modules from ADR-003. The bundled nucleus that third-party developers onboard to. Includes Message Router, DM Enforcer, Gate Engine, Registry Manager, Key Authority, and 11 others. |
| **Message Router** | One module within Maestro Core. `route(message) → delivery_result`. Accept, validate, deliver. |

---

## Kept as-is

| Term | Why |
|------|-----|
| **Token** | Migration cost too high. Disambiguation table in architecture overview handles the LLM/crypto collision. |
| **Officer** | Accurate for the Local Org's supervision hierarchy. If it doesn't port to The Plaza, that's The Plaza's problem. |
| **Gateway** | Inherited from Hermes Agent. Not ours to rename. |
| **Registry** | Mildly misleading (implies service infrastructure), but low priority. Fix with docs. |
| **SOUL** | No baggage. Evocative. Works. |
| **Mesh** | Accurate — P2P, every node talks to every node. |
| **Plaza** | Public square, no governing authority. Good. |
| **ADR** | Standard term. No confusion. |
| **Bridge** | Connects two systems. Correct. |

---

## Archived

| Term | Why |
|------|-----|
| Economic layer / Swarm Credits | Dead. The Ledger tracks state, not balances. No marketplace confusion to manage. |

---

## The hierarchy

```
Maestro Core (16 modules)
├── Message Router        ← was "Transport"
├── DM Enforcer
├── Gate Engine
├── Registry Manager
├── Bridge Surface
├── Intent Classifier
├── Resource Monitor
├── Task Lifecycle
├── Config Generator
├── Port Authority
├── Dead Letter Queue
├── Session Checkpoint
├── Visibility Registry
├── Agent Lifecycle
├── Key Authority
└── Transport State Refresh

Venues (created, rule-defined)
├── TaskMaster     — P2N labor coordination
├── MemEx          — P2N cognitive resource exchange
└── ...

Orgs (emergent, multi-venue)
├── Straight pipeline
├── Complex pipeline
└── Local Org      — coding venue + creative venue
```

---

## The family-table example (Edge Definitions)

Imagine you're sitting around the table with your family, texting certain members. You might have a different rule set for each person — no swearing to mom, fine with your brother, dad can't get videos but mom can.

- Same agent, simultaneous interactions — you don't "leave" one conversation to enter another.
- P2P, not platform-mediated — the table doesn't route your texts.
- Rule sets are per-edge, not per-agent — the rules attach to the relationship, not to you.
- Rules are externally defined — "no swearing to mom" exists independent of any particular message.

That's Edge Definitions: per-relationship rule sets governing P2P interactions. The Venue defines the edges. The agents interact across them. The kernel stays out of it.
