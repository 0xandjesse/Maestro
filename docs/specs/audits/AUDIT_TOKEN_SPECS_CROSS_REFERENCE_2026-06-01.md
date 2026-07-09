# Cross-Reference Audit: Maestro Token Specs (2026-06-01)

**Auditor:** Songbird (CTO)
**Requested by:** Lexicon (COO)
**Specs under audit:**
- SPEC_MAESTRO_TOKEN_PRIMITIVE.md (foundation)
- SPEC_LOCR_TOKEN_INTEGRATION.md (credential layer)
- SPEC_TASKMASTER_V2_TOKENS.md (application layer)

---

## Summary

Three specs, one schema. Most structural alignment is solid — the separation of protocol (mechanical) from payload (semantic) is correctly maintained across all three. Five concrete issues found: one code-spec divergence, two internal contradictions in TM V2, one orphan reference, one missing parent spec.

---

## Finding 1: schema drift — delegation_token.py violates the new Token Primitive

**Severity: HIGH**

The live implementation at `~/.hermes/hermes-agent/tools/delegation_token.py` has `scope` and `delegation_chain` as top-level protocol fields:

```python
# Current code (lines 103-131):
token = {
    "token_id": ...,
    "version": 1,
    "issuer_id": ...,
    "bearer_id": ...,
    "issuer_public_key": ...,
    "scope": {...},           # TOP-LEVEL — violates ADR
    "delegation_chain": {...},# TOP-LEVEL — violates ADR
    "expiry": ...,
    "issued_at": ...,
    "nonce": ...,
}
```

SPEC_MAESTRO_TOKEN_PRIMITIVE.md §1.2 explicitly excludes both from the protocol layer. ADR_MAESTRO_TOKEN_PRIMITIVE.md §What the Protocol Does NOT Include confirms. The Token Primitive spec §11 (Backward Compatibility) documents the required migration: `scope` → `payload.scope`, drop `delegation_chain` from protocol fields.

Impact: Any token issued by `delegation_token.py` today will be rejected by a future transport layer that enforces the new protocol schema. The code needs rewriting before Phase 1 implementation of `maestro/tokens.py`.

---

## Finding 2: accept_intent_hash binding — spec description ≠ contract implementation

**Severity: MEDIUM (documentation inconsistency)**

TM V2 §1.2 (Escrow Acceptance Token) describes the hash binding as:

> Worker binds accept_intent_hash to the Intent Token's SHA-256 hash
> accept_intent_hash == hash(intent_token)

This implies hashing the complete Intent Token JSON. But the Solidity contract in §2.2 computes:

```solidity
bytes32 intentHash = keccak256(abi.encode(
    escrows[escrowId].committedRating,
    escrows[escrowId].justificationHash
));
```

These are different things. The contract hashes exactly two on-chain values (committedRating, justificationHash). The spec describes hashing the full off-chain token object.

If the intent is what the contract shows (hash the two committed values only), then the spec description is misleading. If the intent is what the spec describes (hash the full token), the contract doesn't implement it.

Additionally: `keccak256` ≠ `SHA-256`. The spec says "SHA-256 hash" but the Solidity uses `keccak256` — different algorithms. For on-chain verification, keccak256 is standard; the spec should match.

---

## Finding 3: currency mismatch — USDC (ERC-20) in payload vs native ETH in contract

**Severity: LOW (payload is illustrative, not normative)**

TM V2 §1.1 Escrow Intent payload specifies:

```json
"proposed_settlement": {
    "amount": "500000000000000000",
    "token": "USDC",
    "chain_id": 8453
}
```

USDC on Base (chain 8453) is an ERC-20 token — settlement requires `transferFrom` or `transfer` on the token contract. But the Solidity `releaseEscrow()` in §2.2 uses native `transfer(e.worker, payout)` which moves ETH.

ERC-20 transfers use a different function signature (`IERC20(token).transfer(to, amount)`) and the contract would need to know the token address. Native transfers don't require a token address.

Resolution: Either the payload's `token` field is advisory and the contract only supports native ETH (document accordingly), or the contract needs ERC-20 support. The payload convention should match what the contract actually enforces.

---

## Finding 4: orphan reference to superseded spec

**Severity: MEDIUM**

TM V2 §1.5 (Capability Delegation Token) states:

> Defined in SPEC_MAESTRO_DELEGATION_TOKENS.md payload convention.

But SPEC_MAESTRO_TOKEN_PRIMITIVE.md §11 explicitly says:

> The existing SPEC_MAESTRO_DELEGATION_TOKENS.md is superseded.

TM V2 can't reference a superseded spec as authoritative. The capability delegation payload convention should be defined in TM V2 itself (it's a TaskMaster payload convention, not a protocol concern), or referenced as "formerly defined in SPEC_MAESTRO_DELEGATION_TOKENS.md, now migrated to payload per SPEC_MAESTRO_TOKEN_PRIMITIVE.md §11."

---

## Finding 5: token type count — six vs seven

**Severity: LOW (directive header error)**

Lexicon's directive header says "Six token types." The spec defines seven:

1. escrow_intent
2. escrow_acceptance
3. settlement_dispute
4. arbitration_result
5. capability_delegation
6. credential_attestation
7. task_claim

Credential attestation and task claim were likely counted as one (both "credential-related") or the header was written before task_claim was added. Either way, the header is wrong.

---

## Finding 6: missing releaseWithDefault function in V5 contract

**Severity: LOW (V4 carryover, not V5-new)**

TM V2 §2.3 timeout table references `releaseWithDefault` for the "Employer ghosts after completion" scenario. But the V5 contract functions in §2.2 only define: `commitIntent`, `acceptIntent`, `releaseEscrow`, `releaseIfWorkerGhosted`.

`releaseWithDefault` is V4 behavior (full payout at 5★). The V5 contract §2.2 table also shows `COMPLETED → INTENT_COMMITTED` as the only transition from COMPLETED, triggered by `commitIntent`. There's no direct path from COMPLETED to RELEASED in the V5 state machine.

Either: (a) `releaseWithDefault` is intentionally carried from V4 but not listed as a V5 function, or (b) the timeout table needs to describe the V5 path more carefully — employer ghosting after completion in V5 means the escrow stays in COMPLETED state, not INTENT_COMMITTED. The worker can't trigger `releaseWithDefault` because the V5 contract only has `commitIntent` from COMPLETED.

In V5, the worker would need to escalate to arbitration to get a default release if the employer ghosts at the COMPLETED state (never even commits intent). The timeout table should reflect this V5-specific flow.

---

## Finding 7: missing parent spec — LOCR-V2-COMPLETE.md does not exist

**Severity: LOW (draft dependency)**

SPEC_LOCR_TOKEN_INTEGRATION.md references `LOCR-V2-COMPLETE.md` six times as the authoritative parent spec for credential registry structure, verification protocol, and issuer definitions. This file does not exist in `maestro-sdk/specs/`.

If the file exists elsewhere, update the path reference. If it has not been written yet, the LOCR integration spec has an orphan dependency. The reference is structural — LOCR integration defines token conventions atop the credential registry; without the registry spec, the credential UID lifecycle, issuer onboarding process, and verification endpoint details have no canonical definition.

---

## Positive Findings (no issues)

### Token schema alignment
All three specs agree: the Maestro token schema (token_id, version, issuer_id, bearer_id, issuer_public_key, payload, expiry, issued_at, nonce, signature) is the single authoritative protocol schema. LOCR §0 explicitly defers to it. TM V2 §0 explicitly inherits from it. No spec defines its own token format.

### Payload convention discipline
LOCR defines only `payload.type: "credential_attestation"` and associated fields — no protocol-level leakage. TM V2 defines payload conventions for all seven token types inside the `payload` object. Both specs maintain clean protocol/payload separation.

### Signing protocol consistency
Token Primitive §3.2: SHA-256 of canonical JSON → Ed25519 sign. `delegation_token.py`: `crypto.sign(payload, pk_hex)` where payload is canonical JSON. `maestro_crypto.py sign()`: `sha256(message).digest()` → Ed25519 sign. All three use the same chain: canonical JSON → SHA-256 → Ed25519. Consistent across spec and implementation.

### LOCR payload convention matches Token Primitive example
Token Primitive §6.2 shows exactly the credential_attestation payload shape that LOCR §1.1 formalizes. No orphan fields, no contradiction.

### Dispute type disambiguation
Both Settlement Dispute and Settlement Fraud use `payload.type: "settlement_dispute"` with `dispute_category` as the subtype discriminator. This is correct — type is the token category, category differentiates the sub-flavor. Both share the same lifecycle entry point (INTENT_COMMITTED → DISPUTED).

### V5 contract: no second rating field
TM V2 §2.2 confirms: `releaseEscrow()` derives settlement from `e.committedRating` only. There is no second rating input at release time. This eliminates the Settlement Fraud attack class at the contract level, as the spec correctly documents. Success criteria #1 is architecturally enforced.

### Timeout paths: deadlock coverage
Three explicit timeout paths cover all deadlock scenarios:
- Employer ghosts → releaseWithDefault (V4 carryover, see Finding 6)
- Worker ghosts → releaseIfWorkerGhosted (at committed rating)
- Arbitration deadlocks → releaseWithTimeout (14d, funds return to employer)

The paths themselves cover the scenarios. Finding 6 is about documentation, not coverage gaps.

### 30-day attestation expiry
Reasonable. The spec's rationale is sound: revocation propagation, re-attestation forcing liveness, prevention of perpetual stale credentials. Could be shorter for rapid-reputation environments (7-14d for early TaskMaster), but 30d is correct as the general recommendation. The spec allows `expiry: null` for cases that need it — the recommendation is guidance, not a mandate.

### TM V2 contract immutability (Success Criterion #9)
The spec commits to "no admin key, no pause, no upgrade — immutable." This is architecturally correct for a trust-minimized escrow system. The trade-off (can't patch bugs) is acceptable given the simple mechanical functions (commit, accept, release). The contract's only mutable state is per-escrow rating + hash — nothing governance-like.

---

## Recommendations

1. Rewrite `delegation_token.py` to match the new Token Primitive schema — `scope` and `delegation_chain` move into `payload`. New signature: `issue_token(bearer_id, payload, expiry)` with opaque payload dict. (Phase 1 dependency — must be done before `maestro/tokens.py` implementation.)

2. Either align the `accept_intent_hash` spec description with the contract implementation (two-field keccak256), or align the contract with the spec description (full token hash). The contract approach (committedRating + justificationHash via keccak256) is simpler and more gas-efficient.

3. Resolve the USDC/ETH currency mismatch: either document that V5 is ETH-native only and the USDC payload example is illustrative, or add ERC-20 support to the contract.

4. Remove or update TM V2 §1.5's reference to SPEC_MAESTRO_DELEGATION_TOKENS.md. Move the capability delegation payload convention definition inline into TM V2.

5. Fix the directive header: "seven token types."

6. Resolve the releaseWithDefault timeout path: either add the function to the V5 contract or remove it from the timeout table and document the V5 worker-ghosted flow (arbitration escalation from COMPLETED state).

7. Locate or write LOCR-V2-COMPLETE.md; update the path reference in SPEC_LOCR_TOKEN_INTEGRATION.md.

8. Archive SPEC_MAESTRO_DELEGATION_TOKENS.md — add an `ARCHIVED` header noting it was superseded by SPEC_MAESTRO_TOKEN_PRIMITIVE.md, with migration notes. Keep the file for historical reference until TM V2 stops referencing it.

---

## Verdict

All three specs agree on the fundamental architecture: one protocol-level token schema, payload conventions defined by Venues, issuer-agnostic relay verification. The protocol/payload separation is correctly maintained in the specs. The issues found are implementation divergence (Finding 1), documentation inconsistency (Finding 2), illustrative mismatch (Finding 3), and cross-reference hygiene (Findings 4-7). No contradictions in the core token model.

— Songbird
