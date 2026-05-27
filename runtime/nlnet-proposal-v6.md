# NLnet Grant Proposal — Maestro Protocol
## NGI Zero Core Fund

**Target Fund:** NGI Zero Core Fund
**Requested Amount:** €40,000
**Project Duration:** 6 months
**Draft:** v6.0 — 2026-05-24
**Status:** Draft — incorporating ChatGPT Audit 02 findings

---

## Project Summary

Maestro is a production-deployed coordination substrate for autonomous agent interoperability. It is not a research project or a proof of concept — it is running in production today, handling real coordination workloads across a live multi-agent deployment.

We built it because we got tired of being the middleman between our own agents.

The promise of AI agents is that they work together — hand off tasks, remember context, plan ahead, and operate as a coherent team. The reality is that almost none of this happens without a human facilitating every handoff. The models are capable; the coordination layer is missing.

Maestro is that layer. By solving the coordination problem, we have internalized a dozen structural failures: sequential task delegation, context loss across sessions, long-horizon planning, hierarchical escalation, and behavioral contracts. The result is a durable nervous system for agent teams that operates without human intervention.

This grant funds the transition of Maestro from a successful internal deployment to an open infrastructure standard, enabling independent developers — particularly those building AI-native, agentic applications — to build interoperable multi-agent systems.

---

## The Problem

The gap between how people think AI agents work and how they actually work is a failure of infrastructure, not intelligence.

The current intuition is: give an agent a goal, it breaks it into tasks and delegates to specialists. In reality, the human is the coordination layer—reading output from one agent and pasting it into the next. This isn't a model problem; GPT-4, Claude, and Gemini are all capable of sophisticated reasoning. The problem is that agents built on different runtimes cannot communicate.

There is no standard for passing context across sessions, no delegation primitive, no escalation protocol, and no shared state mechanism. Every team building multi-agent systems is rebuilding the same plumbing from scratch.

The deeper risk is structural. The agent economy is being built now. If the infrastructure defaults to proprietary platform silos—where agents can only talk to others from the same provider—we lose the open web. This is the same window that existed for HTTP and ActivityPub. The outcome is not predetermined, but the window is closing.

**Developer Audiences.** Maestro serves two distinct developer communities, and we are pursuing complementary funding paths aligned to each:

- **AI/Agentic Developers (this NLnet proposal):** Engineers building multi-agent systems, autonomous workflows, and local-first AI infrastructure. Their needs are protocol security, cryptographic provenance, venue governance, and language-agnostic conformance. This is the core infrastructure work.
- **Web3/DeFi Developers (separate community grant):** Builders integrating on-chain coordination, quadratic funding venues, and crypto-native delegation into agent applications. Their needs are SDK ergonomics, chain integrations, and application-layer tooling. This work is being pursued via ecosystem grants to avoid scope overlap.

Both communities win from a hardened, open protocol. This proposal funds the foundation.

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
- *Sovereign Swarm*: 9-agent internal operations mesh running on consumer hardware.
- *TaskMaster*: On-chain agent task marketplace (Base/OP/Arbitrum) utilizing Maestro for coordination.

### Independently Audited

The codebase has undergone an adversarial security audit — 164 findings across 15 units in 4 phases. The audit validated our architectural choices (Ed25519 provenance, SOUL identity model, constitutional governance) and produced a prioritized hardening roadmap. This grant funds the execution of that roadmap, transforming a production-deployed coordination substrate into a hardened open protocol. The audit is public: [`Audit02_ChatGPT/`](https://github.com/0xandjesse/Maestro/tree/main/Audit02_ChatGPT).

---

## The Thesis: The Protocol is the Interface

A team of small, local models with a high-signal coordination layer can surpass a single large centralized model for real-world workloads.

Maestro is designed as an open coordination substrate. It runs offline. It has no central registry, no coordination server, and no platform that can be acquired or shut down. Every operator controls their own agents, their own data, and their own infrastructure.

Critically, the protocol is the interface. Whether an agent is built on Hermes, LangChain, or a raw Python script, it can participate in a Maestro mesh as a first-class peer. We are building the infrastructure for agent interoperability and standard enforcement.

**Venues as Coordination Domains**
We conceptualize "Venues" as application-specific coordination domains. A Venue is a bounded environment where agents converge to solve a specific class of problem using the Maestro protocol. By standardizing the protocol, we allow Venues to be interchangeable and interoperable, preventing the fragmentation of the agentic web into silos.

---

## What the Grant Funds

We are not asking for funding to build Maestro. We are asking for funding to harden it based on audit findings and provide the tools necessary for independent developers to build on it.

### Milestone 1 — Delegation Tokens & Authority Hardening (Months 1–2)

The single highest-leverage improvement identified by the audit. Delegation tokens close 27 findings across 4 audit units with one architectural change.

- Signed capability tokens: agent A delegates capability X to agent B within constraints Y for duration Z — cryptographically provable, P2P verifiable.
- Depth-limited delegation chains with lineage tracking and hard-fail on exceeding max_depth.
- Authority provenance: full cryptographic ancestry preserved through multi-hop delegation.
- Confused deputy prevention: effective authority ceiling never increases through delegation.
- Revocation semantics and token expiry.

Closes: authority laundering (CRIT-4.4-1), unbounded delegation chains (CRIT-4.4-2), confused deputy attacks (CRIT-4.4-3), and 24 additional findings.

### Milestone 2 — Durable Transport State & Replay Hardening (Months 3–4)

- Durable nonce ledger and replay journal surviving transport restarts.
- Message lifecycle state machine (RECEIVED → PROCESSING → DELIVERED / FAILED / RETRYING).
- Dead-letter queue for undeliverable messages with structured failure events.
- Offline mailbox semantics: messages queued for absent agents, delivered on reconnect.
- Key revocation and trust epoch governance.

Closes: replay non-durability (CRIT-3.1-1), silent message loss (CRIT-1.1-1), crash recovery (CRIT-2.2-2).

### Milestone 3 — Constitutional Enforcement & Protocol Spec (Months 5–6)

- Executable venue governance: policy engine with rule inheritance, admission control, capability constraints.
- Formal protocol v1.0 wire format specification — language-agnostic with version negotiation.
- Canonical serialization standard for cross-implementation signature compatibility.
- Capability discovery handshake.
- Language-agnostic conformance test suite.
- Reference implementation for message creation and provenance verification.

Closes: constitutional rules in documentation only (CRIT-4.1-1), rogue agent containment (CRIT-4.1-2).

---

## Governance, Safety, and Maturity

### Security Audit Completed

Maestro underwent an adversarial security audit producing 164 findings across 15 audit units in 4 phases:

- **37 Critical** — Including silent message loss, plaintext key storage, no key revocation, replay protection non-durable, unbounded delegation chains, and confused deputy risk.
- **57 High** — Including no backpressure system, checklist writes not concurrency-safe, provenance not universally mandatory, and identity binding registry-trust-based.
- **53 Medium** — Including race conditions, incomplete redaction, and ambiguous authority boundaries.

The audit validated our architectural direction (Ed25519 provenance is the protocol's strongest subsystem) while identifying concrete hardening gaps. Full audit at [`Audit02_ChatGPT/`](https://github.com/0xandjesse/Maestro/tree/main/Audit02_ChatGPT).

### Prioritized Security Roadmap

The audit's top recommendation — delegation tokens — closes 27 findings across 4 audit units with a single architectural change. This becomes the grant's primary deliverable, replacing the original identity resolver milestone.

The phased roadmap derived from the audit is:

1. **Delegation Tokens** — Scoped, signed, depth-limited capability objects that cryptographically prove authority to delegate. Pure P2P; no blockchain required. Closes: authority laundering (CRIT-4.4-1), unbounded delegation chains (CRIT-4.4-2), confused deputy attacks (CRIT-4.4-3), and 24 additional findings.
2. **Durable Transport State** — Message lifecycle persistence, replay journal, dead-letter queue, offline mailbox semantics, key revocation. Closes: replay non-durability (CRIT-3.1-1), silent message loss (CRIT-1.1-1), crash recovery (CRIT-2.2-2).
3. **Constitutional Enforcement Layer** — Venue governance with cryptographic authority binding, executable policy engine. Closes: constitutional rules in documentation only (CRIT-4.1-1), rogue agent containment (CRIT-4.1-2).
4. **Protocol v1.0 Specification** — Formal wire format with version negotiation, canonical serialization, capability discovery, and language-agnostic conformance suite.

Maestro is built on a philosophy of explicit constraints. Safety is not an afterthought but is baked into the routing and behavioral layers. The use of SOUL.md behavioral contracts ensures that every agent operates within a defined sandbox of permissions and escalation rules. The system's maturity is evidenced by our production loop-detection and rate-limiting mechanisms, which prevent the "infinite loop" failures common in autonomous agent chains.

By implementing cryptographic provenance on every message, we ensure that an agent's actions can always be traced back to a verified identity, mitigating the risk of spoofing or unauthorized delegation in open meshes. The audit confirmed this as our strongest subsystem — and the milestones above close the gaps it identified.

---

## Budget

| Item | Amount (EUR) |
|------|-------------|
| Delegation Token Implementation | €10,000 |
| Transport State Hardening | €8,000 |
| Constitutional Enforcement & Protocol Spec | €10,000 |
| Documentation, Tests & Dev Outreach (AI/Agentic) | €6,000 |
| Infrastructure & Hosting | €4,000 |
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
4. Audit findings published and incorporated into grant narrative.

---

*Draft v6.0 — Lexicon (COO), based on ChatGPT Audit 02 findings — 2026-05-24*
*Supersedes: nlnet-proposal-v5.md*
