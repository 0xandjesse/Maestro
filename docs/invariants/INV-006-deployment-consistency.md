# INV-006 — Deployment Consistency

**Status:** Active
**Date Ratified:** 2026-07-06
**Source:** Observed during directive dedup investigation — Proteus and Songbird were running fixed code while Lexicon, Mnemosyne, and Stormtrooper were not. Behavioral diagnosis was impossible until deployment was normalized.

---

## The Invariant

> Before reasoning about observed system behavior, all participating modules MUST be verified to be running the expected deployment version.
>
> If deployment consistency cannot be established, behavioral diagnosis is suspended until the deployment is normalized.

---

## Rationale

Every failure in a mixed-version fleet has two possible explanations:

1. The code is wrong.
2. You're running old code.

You cannot distinguish them. You're debugging blind.

This is not a guideline. It is a prerequisite for meaningful reasoning. Heterogeneous deployments produce noise, not signal.

---

## Scope

This invariant applies to **all agents** in the Maestro organization — Proteus, Songbird, Sentinel, Lexicon, Mnemosyne, Stormtrooper, and any future agents. It is not a Sentinel rule. It is an organizational law.

Any agent asked to diagnose system behavior MUST first verify deployment consistency. If consistency cannot be established, the agent MUST refuse to reason about behavior and instead report the inconsistency.

---

## Enforcement

- **Sentinel:** Phase 0 gate before any ADR review. If INV-006 is not satisfied, reject the investigation with "normalize deployment first."
- **Proteus:** Before any root cause analysis, verify all participants are running the same version.
- **All agents:** If asked "why is X happening?" and deployment state is unknown, the first response should be "let me verify what everyone is running" — not a hypothesis about the code.

---

## Future: Deployment Primitive

The long-term solution is a deployment primitive that eliminates the question entirely:

```
deploy-runtime
    ↓
Restart transports
    ↓
Verify code hash
    ↓
Verify protocol version
    ↓
Smoke test
    ↓
Record deployment ID
```

A deployment ID (e.g., `2026-07-06.4`) becomes authoritative. Bug reports reference it. Everyone knows exactly what software was running. The question "did you restart Lex?" never needs to be asked again.

---

## Related

- **INV-001 through INV-008** (composition model invariants) — see `docs/maestro-composition-model.md` Section 8
- This invariant is organizational (applies to agent behavior), not architectural (applies to system design). Both types are valid.
