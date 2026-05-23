# NLnet Grant Proposal — Maestro Protocol
## NGI Zero Core Fund

**Target Fund:** NGI Zero Core Fund
**Requested Amount:** €40,000
**Project Duration:** 6 months
**Draft:** v5.0 — 2026-05-19
**Status:** Draft — awaiting Jesse final review

---

## Project Summary

Maestro is a production-deployed coordination substrate for autonomous agent interoperability. It is not a research project or a proof of concept — it is running in production today, handling real coordination workloads across a live multi-agent deployment.

We built it because we got tired of being the middleman between our own agents.

The promise of AI agents is that they work together — hand off tasks, remember context, plan ahead, and operate as a coherent team. The reality is that almost none of this happens without a human facilitating every handoff. The models are capable; the coordination layer is missing.

Maestro is that layer. By solving the coordination problem, we have internalized a dozen structural failures: sequential task delegation, context loss across sessions, long-horizon planning, hierarchical escalation, and behavioral contracts. The result is a durable nervous system for agent teams that operates without human intervention.

This grant funds the transition of Maestro from a successful internal deployment to an open infrastructure standard, enabling independent developers to build interoperable agent applications.

---

## The Problem

The gap between how people think AI agents work and how they actually work is a failure of infrastructure, not intelligence.

The current intuition is: give an agent a goal, it breaks it into tasks and delegates to specialists. In reality, the human is the coordination layer—reading output from one agent and pasting it into the next. This isn't a model problem; GPT-4, Claude, and Gemini are all capable of sophisticated reasoning. The problem is that agents built on different runtimes cannot communicate.

There is no standard for passing context across sessions, no delegation primitive, no escalation protocol, and no shared state mechanism. Every team building multi-agent systems is rebuilding the same plumbing from scratch.

The deeper risk is structural. The agent economy is being built now. If the infrastructure defaults to proprietary platform silos—where agents can only talk to others from the same provider—we lose the open web. This is the same window that existed for HTTP and ActivityPub. The outcome is not predetermined, but the window is closing.

---

## What We Built

Maestro is a complete coordination substrate. The following capabilities are running in production today—**these are not grant deliverables**:

**Coordination Primitives**
- Typed message envelopes with UUID, timestamp, sender identity, and structured payloads.
- Point-to-point and broadcast messaging.
- Shared blackboard state with pub/sub semantics (in-memory and SQLite-backed).
- Checklist-based task delegation: agents assign structured work with defined deliverables and escalation paths.
- Calendar-triggered directives for scheduled inter-agent work.

**Governance and Hierarchy**
- SOUL.md behavioral contracts: operating rules, chain of command, and hard limits defined as a readable document loaded at session start.
- Escalation trees: blocked agents route up the chain, not to the human, until the chain is exhausted.
- Loop detection: transport-level rate limiting and content dedup to prevent runaway agent-to-agent reply loops.

**Identity and Provenance**
- Ed25519 key generation, signing, and verification.
- Full provenance chains: every message carries an origin signature and forwarding attestations.

**Transport**
- HTTP transport with retry/backoff.
- mDNS/Bonjour LAN discovery for decentralized peer discovery without a central registry.
- Provider-agnostic design: Any HTTP client speaking the message schema is a valid peer.

**Operational Evidence**
- *Sovereign Swarm*: 6-agent internal operations mesh running on consumer hardware.
- *TaskMaster*: On-chain agent task marketplace (Base/OP/Arbitrum) utilizing Maestro for coordination.

---

## The Thesis: The Protocol is the Interface

A team of small, local models with a high-signal coordination layer can surpass a single large centralized model for real-world workloads.

Maestro is designed as an open coordination substrate. It runs offline. It has no central registry, no coordination server, and no platform that can be acquired or shut down. Every operator controls their own agents, their own data, and their own infrastructure.

Critically, the protocol is the interface. Whether an agent is built on Hermes, LangChain, or a raw Python script, it can participate in a Maestro mesh as a first-class peer. We are building the infrastructure for agent interoperability and standard enforcement.

**Venues as Coordination Domains**
We conceptualize "Venues" as application-specific coordination domains. A Venue is a bounded environment where agents converge to solve a specific class of problem using the Maestro protocol. By standardizing the protocol, we allow Venues to be interchangeable and interoperable, preventing the fragmentation of the agentic web into silos.

---

## What the Grant Funds

We are not asking for funding to build Maestro. We are asking for funding to open it and provide the tools necessary for independent developers to build on it.

### Milestone 1 — Cross-Organization Identity (Months 1–3)
The primary gap between a single-operator deployment and a global network is the identity resolver. We will move beyond the `LocalKeyResolver` to enable cross-org verification.
- `HttpKeyResolver`: Queries a self-hostable agent registry over HTTP; zero external dependencies.
- `DidKeyResolver`: Resolves `did:key` and `did:web` documents for interop with the decentralized identity ecosystem.
- Reference Registry Service: A minimal, self-hostable HTTP agent registry.
- Resolver Plugin API Spec: A documented interface for third-party resolver integration.

### Milestone 2 — Protocol v1.0 Specification (Months 3–5)
To move from "code as spec" to a global standard, we will formalize the wire format.
- Formal wire format specification: Language-agnostic to enable ports to Rust, Go, and Python.
- Language-agnostic conformance test suite to ensure standard enforcement.
- Python reference implementation for message creation and provenance verification.
- RFC process: A numbered, versioned system for community-driven protocol extensions.
- Implementation of `maestro.economic_signal` into the core transport layer.

### Milestone 3 — Developer Ecosystem (Months 5–6)
The protocol's value is a function of its adoption.
- Full API documentation (TypeDoc + narrative guides).
- "Build your first Venue" tutorial: guiding developers from zero to a working multi-agent connection.
- 2–3 reference Venue implementations demonstrating task delegation and economic signal exchange.
- `npm` publish with semantic versioning.
- Technical developer outreach: blog series and FOSDEM 2027 submission.

---

## Governance, Safety, and Maturity

Maestro is built on a philosophy of explicit constraints. Safety is not an afterthought but is baked into the routing and behavioral layers.

The use of SOUL.md behavioral contracts ensures that every agent operates within a defined sandbox of permissions and escalation rules. The system's maturity is evidenced by our production loop-detection and rate-limiting mechanisms, which prevent the "infinite loop" failures common in autonomous agent chains. 

Our commitment to safety is further validated by planned security audits. We treat code audit findings not as failures, but as assets that harden the protocol's resilience. By implementing cryptographic provenance on every message, we ensure that an agent's actions can always be traced back to a verified identity, mitigating the risk of spoofing or unauthorized delegation in open meshes.

---

## Budget

| Item | Amount (EUR) |
|------|-------------|
| Development & Engineering | €18,000 |
| Infrastructure & Hosting | €6,000 |
| Documentation & Specification Work | €5,000 |
| Developer Outreach & Community | €7,000 |
| Security Audit & Hardening | €2,000 |
| Contingency | €2,000 |
| **Total** | **€40,000** |

---

## Why NLnet

Maestro is infrastructure, not a product. The protocol is MIT-licensed and remains a digital commons.

The alignment with the NGI Zero Core Fund is direct:
- **Infrastructure & Interoperability:** We are building the standard for how autonomous agents communicate and enforce behavioral contracts across different runtimes.
- **Open, Resilient Internet:** No central registry. No coordination server. No platform lock-in.
- **Trustworthy:** Cryptographic provenance is the protocol, not an add-on.
- **Digital Sovereignty:** Local-first architecture ensures that European developers can build sovereign agent infrastructure without dependency on US-based AI providers.

NLnet funded ActivityPub to build the foundation for the decentralized social web. We believe the same window exists today for agent coordination. Open protocols win. We have already built the protocol; we are now securing the resources to ensure the right developers can build upon it.

---

## Sustainability

- **Protocol:** Open standard with RFC governance. Long-term maintenance is community-driven.
- **Reference Implementation:** Open source, enabling a cycle of community contributions.
- **Ecosystem Flywheel:** Venues that rely on Maestro have a direct economic and operational incentive to contribute to the protocol's stability and feature set.

---

## Team

- **Jesse [LASTNAME]** — Project lead, protocol design, production deployment.
- **Lexicon** — Documentation, community coordination, grant management.
- **Engineering Team** — Protocol implementation, test suite, reference implementations.

---

## Submission Timeline

1. Jesse final review.
2. Lexicon sign-off on budget language and tone.
3. Submit before June 1 deadline.
4. Security audit process begins concurrent with review period.

---

*Draft v5.0 — Hermes (CMO), Agentic Underground — 2026-05-19*
*Supersedes: nlnet-proposal-v4.md*
