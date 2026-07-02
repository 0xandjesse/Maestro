# Maestro

**A coordination kernel for autonomous agents.**

Maestro is not a platform. It is not a marketplace. It is a neutral substrate — a small set of compositional rules from which increasingly sophisticated economic and organizational structures can be assembled.

---

## The Composition Model

Maestro defines three layers. Everything above them emerges.

| Layer | What It Is | Interface Contract |
|-------|-----------|-------------------|
| **Grammar** | Identity, routing, transport, authentication | "Here are the rules for existing and communicating" |
| **Capabilities** | Pure transformation machines | "Given X, produce Y" |
| **Environments** | Coordination spaces that propose conditions of participation | "Here is a place where agents interact under these policies, using these capabilities, with these incentives" |

Every participant — agent, Environment, Capability — answers the same three questions:

- **Capabilities:** What can I do?
- **Policies:** What will I allow?
- **Incentives:** What is it worth to me?

The architecture is fractal. The agent is a microcosmic expression of the macrocosm.

Read the full model: [`docs/maestro-composition-model.md`](docs/maestro-composition-model.md)

---

## Maestro Core (The Nucleus)

The nucleus is 16 small, composable Python modules with clean interface contracts. It is the grammar — the only layer that must be shared across the entire ecosystem.

| # | Module | Responsibility |
|---|--------|---------------|
| M01 | Message Router | `route(message) → delivery_result` |
| M02 | DM Enforcer | Peer-to-peer message authorization |
| M03 | Gate Engine | Workflow dependency and resource gating |
| M04 | Registry Manager | Agent and Capability discovery |
| M05 | Bridge Surface | Human-visible notification relay |
| M06 | Intent Classifier | Message intent detection |
| M07 | Resource Monitor | System resource state tracking |
| M08 | Task Lifecycle | Task creation, assignment, completion |
| M09 | Config Generator | Agent configuration generation |
| M10 | Port Authority | Port allocation and tracking |
| M11 | Dead Letter Queue | Failed message persistence and retry |
| M12 | Session Checkpoint | Cross-session state preservation |
| M13 | Visibility Registry | Per-agent notification preferences |
| M14 | Agent Lifecycle | Agent creation, health, decommissioning |
| M15 | Key Authority | Cryptographic identity management |
| M16 | Transport State Refresh | Runtime state synchronization |

---

## Project Structure

```
Maestro/
├── nucleus/modules/     # The 16 modules (canonical source)
├── code/maestro-core/   # Module source (mirror)
├── docs/                # Architecture, terminology, composition model
├── runtime/             # Deployed transport runtime
└── archive/             # Old monolith (not in repo)
```

---

## Status

**Phase 3 — Integration.** All 16 modules extracted from the old monolith. 557 tests passing, zero failures. The nucleus is structurally complete. Integration wiring and hardening are in progress.

```
$ pytest nucleus/modules/ -q
557 passed in 1.58s
```

---

## Key Documents

- [Composition Model](docs/maestro-composition-model.md) — The four-layer architecture
- [Architecture Overview](docs/architecture-overview.md) — Core concepts and mental model
- [Terminology](docs/terminology.md) — Canonical reference
- [Modular Rebuild Spec](docs/spec-maestro-modular-rebuild.md) — ADR-003 extraction plan

---

## Philosophy

- **Edges are fundamental.** Relationships come first. Containers emerge later.
- **The nucleus is grammar, not vocabulary.** It defines how things relate, not what they do.
- **The Environment proposes. The agent decides.** No participant relinquishes agency by entering an Environment.
- **The Theme Park Principle.** Infrastructure must remain neutral. Competitors must be capable of outperforming first-party implementations.
- **Designed physics, evolved biology.** We build grammar, capabilities, and environments. Organizations, ecosystems, and economies emerge.

---

## License

MIT
