# INV-007 — Policy Context Sovereignty

**Status:** Active
**Date Ratified:** 2026-07-06
**Source:** ADR-018 (Policy Contexts and Normative Environments)

---

## The Invariant

> **No actor may unilaterally change another actor's policy context. Only the actor itself may activate or deactivate a policy context through voluntary participation.**

---

## Rationale

Policy contexts are actor-owned. An agent's standing policies are its identity. A Venue's participation contract is its governance. An organization's policies are its operating rules.

If any actor could force another into a different policy context, sovereignty is lost. A Venue could override an agent's security requirements. An organization could suppress an agent's provenance checks. A relay could change the rules mid-hop.

The only legitimate way to change an agent's policy context is for the agent to voluntarily enter an environment that requires it — and the agent can leave at any time.

---

## Scope

Applies to all actors in Maestro: agents, Venues, organizations, relays, and any future actor types. No actor — regardless of authority, hierarchy, or capability — may change another actor's policy context without that actor's consent.

---

## Enforcement

- **Transport:** Validates artifacts. Does not change policy contexts.
- **Venues:** Advertise participation contracts. Do not impose them.
- **Agents:** Activate and deactivate their own policy contexts.
- **Relays:** Pass messages. Do not modify policy context declarations.

---

## Related

- INV-006 (Deployment Consistency)
- ADR-017 (Authority Originates with Actors)
- ADR-018 (Policy Contexts and Normative Environments)
