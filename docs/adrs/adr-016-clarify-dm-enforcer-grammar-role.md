# ADR-016 — Clarify the Role of DM Enforcer in the Grammar Layer

**Status:** Done — module renamed to Authorization Verifier (2026-07-08)
**Date:** 2026-07-06
**Author:** Proteus (triggered by Sentinel's ADR-015 Phase 1 review)
**Supersedes:** Clarifies `maestro-composition-model.md` §2.1

---

## 1. Observation

The composition model contains an internal contradiction:

> "Grammar does not make policy decisions." (§2.1, line 42)

> "Grammar is the 16 modules of Maestro Core: Message Router, **DM Enforcer**, Gate Engine..." (§2.1, line 40)

"DM Enforcer" implies policy enforcement — deciding whether Alice may DM Bob. But Grammar is explicitly prohibited from making policy decisions. The word "Enforcer" is overloaded, collapsing two distinct responsibilities into one name.

Sentinel identified this during ADR-015 review:

> "The composition model says 'Grammar does not make policy decisions' AND 'DM Enforcer is a Grammar module.' Those two statements are in tension. The ADR picks one side of the tension and declares the other side wrong, without acknowledging the conflict."

This ADR resolves the tension before ADR-015 proceeds.

---

## 2. Root Cause

The word "Enforcer" conflates two kinds of enforcement:

| Type | Question | Example | Belongs In |
|---|---|---|---|
| **Protocol enforcement** | Is this artifact valid? | Is the signature valid? Is the token authentic? Is the issuer who they claim to be? | Grammar |
| **Policy enforcement** | May this interaction occur? | Should Alice be allowed to DM Bob? Is Bob in Alice's target list? | Policy layer |

Grammar should enforce protocol validity. It should verify that authorization artifacts (tokens, signatures, identity claims) are cryptographically sound. It should not evaluate whether those artifacts grant permission for a specific interaction — that's a policy decision.

The current name "DM Enforcer" suggests the module does both. It should only do the first.

---

## 3. Proposed Change

### 3.1 Rename the Module

**From:** DM Enforcer
**To:** Authorization Verifier

The Authorization Verifier is a Grammar module. It verifies:

- Signature validity on presented tokens
- Issuer identity (is the issuer who they claim to be?)
- Token authenticity (is this token cryptographically sound?)
- Bearer binding (does the presenter match the token's bearer?)

It does NOT verify:

- Whether the bearer is allowed to DM the recipient
- Whether the recipient accepts DMs from this bearer
- Whether the interaction should proceed

Those are policy questions. They belong in the Policy layer.

### 3.2 Update the Composition Model

Replace line 40:

> "Grammar is the 16 modules of Maestro Core: Message Router, DM Enforcer, Gate Engine..."

With:

> "Grammar is the 16 modules of Maestro Core: Message Router, Authorization Verifier, Gate Engine..."

And add a clarifying note:

> "The Authorization Verifier (formerly DM Enforcer) validates authorization artifacts — signatures, tokens, identity claims. It answers 'is this artifact valid?' It does not answer 'may this interaction occur?' Policy evaluation belongs to the Policy layer."

### 3.3 Clarify the Boundary

```
Grammar (Authorization Verifier)
    ↓
"Is this token cryptographically valid?"
"Is the signature correct?"
"Is the issuer authentic?"
"Is the bearer who they claim to be?"
    ↓
    (passes verified artifacts upward)
    ↓
Policy Layer
    ↓
"May Alice DM Bob?"
"Is Bob in Alice's target list?"
"Does the current Venue permit this?"
    ↓
Permitted / Denied
```

---

## 4. Impact on ADR-015

ADR-015 currently claims DM enforcement in the transport is a policy leak. After this clarification:

- The transport SHOULD verify authorization artifacts (signatures, tokens, identity) — that's Grammar
- The transport SHOULD NOT evaluate authorization policy (target lists, permission checks) — that's Policy
- The current `_check_dm_policy` does both — it verifies the token AND checks the target list. The fix is to split these, not remove both.

ADR-015 should be rewritten to:
1. Keep artifact verification in the transport (Grammar)
2. Move policy evaluation (target list checks) to the Policy layer
3. Remove the `dm_policy.enabled` boolean — verification is always-on

---

## 5. What This Resolves

| Before | After |
|---|---|
| "DM Enforcer" — ambiguous scope | "Authorization Verifier" — clearly protocol-level |
| Composition model contradicts itself | Model is internally consistent |
| Unclear what Grammar should enforce | Grammar enforces protocol validity, not social policy |
| ADR-015 argues against the model | ADR-015 can be rewritten against the clarified model |

---

## 6. Open Questions

1. **Where does the Policy layer live?** If target-list checking moves out of transport, where does it go? A Venue module? A per-agent policy file? This is for ADR-015 to resolve.
2. **Migration path:** Does the rename require code changes, or is it purely a documentation clarification? The module name in code (`_check_dm_policy`) should eventually reflect the clarified scope.
