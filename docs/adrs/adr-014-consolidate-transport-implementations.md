# ADR-014 — Consolidate Agent Transport Implementations

**Status:** Deferred (DR Queue)
**Date:** 2026-07-06
**Author:** Sentinel (via Songbird)
**Deciders:** Songbird (CTO), Proteus (Tech Lead)

---

## Context

During implementation of ADR-012 ("Remove Secondary Wake Path"), an architectural boundary fix was applied to every transport implementation. The same change was required in four separate transport files:

- `maestro_transport.py`
- `lulu/maestro_transport.py`
- `stormtrooper/maestro_transport.py`
- `message_router/maestro_transport.py`

The required change was conceptually singular:

> Presentation-layer concerns (splitting, truncation, formatting) do not belong in the transport layer.

However, because the transport exists in multiple copies, the change had to be implemented and verified independently in each location.

This is not currently causing incorrect behavior, but it increases maintenance cost and the probability of future architectural drift.

---

## Problem Statement

The current architecture appears to contain multiple implementations of the same conceptual module. This raises several questions:

- Are these implementations intentionally independent?
- Are they forks that have accumulated over time?
- Are they generated artifacts?
- Are they configuration variants that should instead share a common implementation?

Without answering these questions, every future transport-level architectural change risks requiring synchronized edits across multiple code paths.

---

## Architectural Concern

Multiple implementations of the same module increase the likelihood of:

- Inconsistent bug fixes
- Divergent behavior
- Incomplete security patches
- Architectural drift
- Documentation drift
- Duplicated testing effort

The issue is not code duplication itself. The issue is **ownership**. A conceptual module should ideally have a single authoritative implementation unless there is a deliberate architectural reason for divergence.

---

## Decision

**Deferred.** Do not refactor transport implementations during current Trust Surface stabilization.

Instead:

1. Stabilize the messaging architecture.
2. Complete Event Bus migration.
3. Evaluate whether the transport implementations represent:
   - Independent modules,
   - Generated artifacts,
   - Or configuration variants.

Only after that evaluation should consolidation be considered.

---

## Investigation Required

Determine:

- Why do four transport implementations exist?
- Which behavioral differences are intentional?
- Which differences are historical?
- Can differences be expressed through configuration?
- Would a shared transport core with pluggable adapters better express the architecture?
- Would consolidation reduce future maintenance without introducing undesirable coupling?

---

## Non-Goals

This ADR does **not** assume that a single transport implementation is automatically superior. If the implementations serve distinct architectural purposes, duplication may be justified.

The objective is to determine whether the current duplication is intentional architecture or historical evolution.

---

## Success Criteria

Following investigation, the organization should be able to answer:

> "Why do multiple transport implementations exist?"

with a deliberate architectural explanation rather than historical context.

---

## Rationale

This ADR is being raised after ADR-012 because a single architectural boundary change required synchronized edits across every transport implementation. This is an indicator of possible maintainability debt rather than an active defect.

The goal is not to eliminate duplication for its own sake, but to ensure that module boundaries remain intentional, comprehensible, and sustainable as Maestro continues to evolve.
