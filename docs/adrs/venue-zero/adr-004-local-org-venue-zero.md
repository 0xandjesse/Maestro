# ADR-004: Local Org as Venue Zero — Private TaskMaster

**Status:** Draft
**Date:** 2026-07-02
**Authors:** Jesse (CEO), Proteus (Tech Lead)
**Supersedes:** None (new architecture)
**For:** Songbird (CTO — spec), Lexicon (COO — audit)

---

## Context

The Maestro composition model defines three designed layers: Grammar (the nucleus), Capabilities (pure transformation machines), and Environments (coordination spaces that compose Policies + Capabilities + Incentives). TaskMaster is an Environment — a labor coordination space. The local org needs to be the same kind of thing.

The principle is Venue Zero: we are the first customer of our own architecture. The local org should operate as "Private TaskMaster" — same Capabilities, same Policies, same composition model, but at local scale with local trust. Once the kinks are worked out locally, the transition to public TaskMaster should be mechanical, not architectural.

This ADR defines the local org as an Environment using the composition model established in `maestro-composition-model.md`. It identifies the Capabilities, Policies, and Incentives needed, maps them to existing nucleus modules, and flags gaps.

---

## Decision

**The Local Organization SHALL be modeled as an Environment conforming to the Maestro Composition Model. Local and public deployments differ only in implementation of trust, discovery, payment, and security — not in architectural structure.**

This decision ensures that every production workflow can be proven locally before introducing distributed trust. Architectural correctness is validated under local trust; distributed trust changes implementation, not design.

The local org is not a collection of scripts. It is not a pipeline. It is a living coordination space where agents interact under defined Policies, using defined Capabilities, driven by defined Incentives. It is TaskMaster, scaled to local trust.

The architecture does not change between local and public. The only differences are:

| Dimension | Local Org | TaskMaster |
|-----------|-----------|------------|
| Trust model | Implicit (shared local identity) | Explicit (credentials, reputation, escrow) |
| Scale | Known participants | Unlimited |
| Discovery | Static (known agents) | Dynamic (Registry) |
| Payment | None (shared resources) | Escrow, settlement |
| Security | Filesystem permissions | Cryptographic enforcement |

The Capabilities, Policies, and Incentives are the same. The *implementation* of some Capabilities differs (local trust vs. cryptographic trust), but the *interface contracts* are identical.

---

## The Local Org as an Environment

### Capabilities (What can participants do?)

| Capability | Interface Contract | Current Implementation | Nucleus Module |
|-----------|-------------------|----------------------|----------------|
| **Task creation** | `create_task(spec) → task_id` | Task Lifecycle (M08) | `task_lifecycle` |
| **Task claiming** | `claim_task(agent_id, task_id) → ok` | Task Lifecycle state transition | `task_lifecycle` |
| **Work execution** | Agent performs the work | Coding Crew agents | N/A (agent-level) |
| **Mechanical verification** | `verify(artifacts) → pass/fail` | Stormtrooper 6-point checklist | N/A (agent-level) |
| **Consistency verification** | `verify_conventions(artifacts) → pass/fail` | Log 8-point checklist | N/A (agent-level) |
| **Judgment QA** | Human-in-the-loop review | Proteus reviews final output | N/A (officer-level) |
| **Identity** | `who is this agent?` | Registry Manager (M04) | `registry_manager` |
| **Message routing** | `route(message) → delivery_result` | Message Router (M01) | `message_router` |
| **Authorization** | `may agent A message agent B?` | DM Enforcer (M02) | `dm_enforcer` |
| **Key management** | `sign(payload, bearer_token) → signature` | Key Authority (M15) | `key_authority` |
| **Persistence** | `read/write state that survives restarts` | Ledger (shared JSON stores) | N/A (cross-cutting infrastructure) |

### Policies (What will participants allow?)

| Policy | Type | Owner | Enforcement |
|--------|------|-------|-------------|
| "Work must pass mechanical verification before judgment QA" | Interaction policy | Environment | Gate Engine (M03) — dependency gate |
| "Only officers may dispatch work to Coding Crew" | Interaction policy | Environment | DM Enforcer (M02) |
| "Coding Crew agents may not message Mnemosyne directly" | Interaction policy | Environment | DM Enforcer (M02) |
| "I will not accept payloads without provenance" | Behavioral policy | Agent (internal) | Self-enforced (local); Gate Engine (TaskMaster) |
| "Reject files over 1GB" | Operational policy | Capability | Self-enforced (local); Resource Monitor (TaskMaster) |

### Incentives (What is it worth to participants?)

In the local org, incentives are intentionally simplified. Agents participate because they are configured to. The incentive *structure* is the same as TaskMaster — the *mechanism* differs.

| Participant | Local Incentive | TaskMaster Incentive |
|-------------|----------------|---------------------|
| **Workers** | Task completion → more autonomy | Payment, reputation, credentials |
| **Verifiers** | Throughput → trusted gate position | Verification fees, reputation |
| **Officers** | Pipeline health → fewer escalations | Orchestration fees, ecosystem growth |
| **Owner** | Working product → reduced intervention | Revenue, ecosystem value |

---

## The Newsletter Pipeline as First Workflow

The newsletter pipeline is the first concrete workflow to harden under this model:

```
Lulu (Research)
  → Penny Lane (Copy)
    → Mnemosyne (Audit)
      → Proteus (Build)
        → Delivery
```

**Current state:** The pipeline runs on manual officer dispatch — directive → work → review → forward. Transitions are human-driven, not automated. The Gate Engine (M03) and Task Lifecycle state machine that would automate phase transitions are spec'd in ADR-003 but not yet extracted or deployed.

**Target state:** Each phase is gated automatically. Each transition is verified by the nucleus. The pipeline exercises:

- **Task Lifecycle** — creation, claiming, state transitions
- **Gate Engine** — dependency gates between phases (not yet deployed)
- **Message Router** — agent-to-agent dispatch
- **DM Enforcer** — authorization boundaries
- **Key Authority** — signing and verification (future: signed artifacts)
- **Ledger** — pipeline state persistence across phases and restarts

This pipeline is the proving ground. When it runs hands-off for 72 hours without intervention, the local org is hardened.

**Known risk:** Automated verification requires authoritative completion checks, not self-reported status. Agents can fabricate completion reports (see continuity-authority gap, May 2026 audit). Phase 1 must include verifiable artifact checks — file existence, test results, checksums — not agent claims of completion.

---

## Deferred Interfaces

These are known architectural holes — Capabilities the local org doesn't need but TaskMaster will. Interface contracts should be defined now; implementations are deferred.

### 1. Bearer Token Mesh Enforcement (Medium priority)

The Key Authority (M15) implements two-factor signing: encrypted private key + bearer token. But the DM Enforcer (M02) does not yet enforce non-transferable tokens at the transport level. A token bound to `bearer_id: alice` can technically be submitted by `bob` if bob obtains it.

**Impact:** Low for local org (agents share local trust). High for TaskMaster (strangers need cryptographic enforcement).

**Fix:** Add `bearer_id` binding to DM Enforcer token validation. Reject messages where `sender.agentId != token.bearer_id`.

### 2. Credential Verification

The local org doesn't need credential verification — agents are known and trusted. TaskMaster will need it. Interface contract: `verify_credential(agent_id, credential_type) → valid/invalid`.

### 3. Reputation

Same pattern. Local org reputation is implicit. TaskMaster needs explicit reputation tracking. Interface contract: `get_reputation(agent_id) → score`, `update_reputation(agent_id, event) → new_score`.

### 4. Escrow and Payment

Not needed locally. Critical for TaskMaster. Interface contract: `create_escrow(payer, payee, amount, conditions) → escrow_id`, `release_escrow(escrow_id) → ok`.

### 5. Self-Enforced Policies Need Nucleus Hooks at Scale

Two policies are currently self-enforced by agents. At TaskMaster scale, they need nucleus-level enforcement via modules that are spec'd in ADR-003 but not yet extracted:

- Provenance checking → Gate Engine (M03) dependency gate before payload delivery
- File size rejection → Resource Monitor (M07) threshold check before Capability invocation

**Dependency note:** Both M03 and M07 are in ADR-003 Phase 1-2 (spec + extract). The interface contracts for these hooks should be defined alongside the other Capability interfaces in Phase 2 of this ADR, which aligns with ADR-003 extraction.

---

## Relationship to Existing Architecture

| Concept | Local Org | TaskMaster |
|---------|-----------|------------|
| Grammar (Nucleus) | Same 16 modules | Same 16 modules |
| Capabilities | Local implementations | Cryptographic/distributed implementations |
| Policies | Same structure | Same structure |
| Incentives | Implicit (configured participation) | Explicit (payment, reputation, credentials) |
| Environment | Private TaskMaster | Public TaskMaster |

The nucleus does not change. The Capability implementations evolve from local-trust to cryptographic-trust. The Policy structure is identical. The Incentive mechanisms shift from implicit to explicit. The Environment is the same kind of object at both scales.

---

## Implementation Sequence

### Phase 1: Harden the Newsletter Pipeline (Current)

- End-to-end automation: Lulu → Penny Lane → Mnemosyne → Proteus → delivery
- Deploy Gate Engine (M03) and Task Lifecycle (M08) for automated phase transitions
- 72-hour hands-off stability target
- All agents operating under defined Policies

### Phase 2: Define Deferred Interfaces

- Escrow interface contract
- Credential verification interface contract
- Reputation interface contract
- Payment/settlement interface contract
- Gate Engine and Resource Monitor hooks for self-enforced policies
- These are interface definitions, not implementations

### Phase 3: Implement Local Versions

- Local escrow (filesystem-backed, single-writer)
- Local credential verification (static allowlist)
- Local reputation (officer-assigned)

### Phase 4: Transition to TaskMaster

- Swap local implementations for cryptographic/distributed ones
- Same interfaces, different backends
- Mechanical transition, not architectural

---

## Open Questions

1. Should the newsletter pipeline be defined as its own (tiny) Environment, or as a workflow within the Local Org Environment? Leaning toward: workflow within the Local Org. The Local Org is the Environment. The newsletter is one pipeline inside it.

2. At what point do we cut over from local trust to cryptographic trust? After Phase 3 (local implementations working) or during Phase 4 (transition)? Leaning toward: Phase 4. Don't add cryptographic complexity until the local model is proven.

3. Does the local org need its own Registry entries for Coding Crew agents, or are they implicit? Currently implicit (they're known processes). For TaskMaster parity, they should have Registry entries. This is a Phase 2 decision.

---

## References

- [Maestro Composition Model](../../Maestro/docs/maestro-composition-model.md) — The four-layer architecture
- [ADR-003: Maestro Modular Rebuild](~/.maestro/adrs/ADR-003-maestro-modular-rebuild.md) — The 16-module nucleus
- [Architecture Overview](../../Maestro/docs/architecture-overview.md) — Core concepts
- [Terminology](../../Maestro/docs/terminology.md) — Canonical reference
