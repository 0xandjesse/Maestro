# Spec: Maestro Token Primitive

**Status:** Draft v1 — replaces SPEC_MAESTRO_DELEGATION_TOKENS.md
**Author:** Lexicon (COO)
**Date:** 2026-06-01
**Philosophical Foundation:** ADR_MAESTRO_TOKEN_PRIMITIVE.md (Jesse, 2026-05-29)
**Purpose:** Standalone specification for the Maestro token primitive — a protocol-level mechanism for creating, exchanging, validating, and revoking signed artifacts. This is a protocol primitive, not an application feature. All downstream systems (TaskMaster, LOCR, Venues, Plaza) inherit the same primitive.

---

## 0. Philosophy

> **Maestro does not define token meaning. Maestro provides primitives. Venues provide semantics. Agents provide interpretation.**

A token is a **signed artifact**. Nothing more.

The protocol concerns itself only with mechanical operations: issue, sign, verify, revoke, expire, transfer (future), provenance track. The protocol does NOT define `type`, `scope`, `actions`, `resources`, `venues`, `allow_delegation`, or any other higher-order field. Those belong to the payload layer — defined by the consuming Venue, not by the protocol.

**Why this matters:** Defining token types at the protocol layer creates long-term governance burden. Every new coordination pattern requires a protocol change. A neutral token primitive avoids this entirely. The protocol remains stable while an unlimited number of token-based systems emerge above it.

---

## 1. Token Schema (Protocol-Level)

```json
{
  "token_id": "<uuid>",
  "version": 1,
  "issuer_id": "<agent_id>",
  "bearer_id": "<agent_id>",
  "issuer_public_key": "<Ed25519 hex>",
  "payload": {},
  "expiry": null,
  "issued_at": "<unix timestamp>",
  "nonce": "<random 32 bytes hex>",
  "signature": "<Ed25519 signature over all fields above>"
}
```

### 1.1 Protocol-Level Fields

| Field | Purpose | Nullable? |
|-------|---------|-----------|
| `token_id` | Globally unique identifier (UUID v4) | No |
| `version` | Schema version (currently 1) | No |
| `issuer_id` | Agent who created this token | No |
| `bearer_id` | Agent this token was issued to | No |
| `issuer_public_key` | Ed25519 public key for signature verification | No |
| `payload` | Opaque object — Venue/receiver defines meaning | No (can be `{}`) |
| `expiry` | Unix timestamp or `null` for permanent | Yes |
| `issued_at` | Creation timestamp (Unix epoch seconds) | No |
| `nonce` | Random 32 bytes hex — prevents replay | No |
| `signature` | Ed25519 signature over all fields above | No |

> **⚠️ PERMANENT TOKENS:** `expiry: null` creates a token that never expires — it remains valid until explicitly revoked. Use with extreme caution. Permanent tokens accumulate revocation pressure: every permanent token issued creates an indefinite obligation to maintain revocation state. **Recommendation:** default to short-lived tokens (hours to days). Use `null` only when the token's lifetime genuinely matches the underlying authorization (e.g., permanent contact grants, venue membership). If you can put an expiry on it, put an expiry on it.

> **ℹ️ NONCE + REPLAY:** The `nonce` field provides uniqueness — no two tokens from the same issuer should share a nonce. However, **the protocol does not store or track nonces**. Replay prevention is a Venue/application concern. A Venue that wants replay protection must track seen nonces (e.g., maintain a Bloom filter of recent nonces per issuer). The protocol provides the nonce; the application decides how long to remember it.

### 1.2 What the Protocol Does NOT Include

No `type` field. No `scope` field. No `actions` array. No `resources` array. No `allow_delegation` flag. No `heartbeat_required` flag. No `venues` field. No `revocation_endpoint`.

All of those are **payload-level interpretations**. The protocol moves signed artifacts. The receiver decides what the payload means.

---

## 2. Protocol Operations

Maestro provides exactly these mechanical operations:

### 2.1 Token Issuance

```
maestro.token.issue(
    bearer_id: str,
    payload: dict,
    expiry: int | None = None
) -> dict  # signed token object
```

Agent signs the token with their `MAESTRO_PRIVATE_KEY`. Returns the signed token object. The `payload` is an opaque dict — the issuer and bearer negotiate its meaning off-protocol.

### 2.2 Token Validation

```
maestro.token.validate(
    token: dict
) -> tuple[bool, str]  # (valid, reason)
```

Verifies:
1. **Signature validity** — Ed25519 verify against `issuer_public_key` over canonical JSON of all fields except `signature`
2. **Registry key resolution** — confirm `issuer_public_key` matches the registered public key for `issuer_id` in the agent registry. Mismatch returns `(False, "issuer_key_mismatch")`.
3. **Expiry** — if `expiry` is set, confirm `now() < expiry`
4. **Revocation status** — check issuer's revocation list

Returns `(True, "ok")` or `(False, "<reason>")`.

> **⚠️ BEARER BINDING WARNING:** `validate_token()` does NOT check that the presenting caller matches `bearer_id`. Protocol validation verifies cryptographic integrity and liveness only. **Venues MUST validate bearer authorization** — accept tokens only from callers matching `token["bearer_id"]`. If a Venue accepts Lexicon's token presented by Stormtrooper, that is a Venue bug, not a protocol bug. This is the single most likely implementation error in token-consuming systems.

### 2.3 Token Revocation

```
maestro.token.revoke(
    token_id: str
) -> bool
```

Issuer invalidates a token they issued. Added to issuer's revocation list. Subsequent validation fails. Only the issuer can revoke.

### 2.4 Revocation Distribution

Revocation discovery is NOT standardized at the protocol level — the protocol does not define how validators learn about revocations. However, it defines a **recommended record format** so that issuers and validators can exchange revocation state in a consistent way:

```json
{
  "token_id": "<uuid>",
  "revoked_at": "<unix timestamp>",
  "issuer_id": "<agent_id>",
  "issuer_signature": "<Ed25519 signature over token_id + revoked_at + issuer_id>"
}
```

**Recommended patterns (not mandated):**

1. **Issuer-published revocation ledger** — each issuer maintains a file at a known path (e.g., `~/.maestro/revocation_logs/{issuer_id}.json`). Validators pull this file periodically.

2. **Signed revocation record broadcast** — when an issuer revokes a token, they broadcast the signed revocation record via the Maestro transport mesh. Validators cache received revocations.

3. **On-demand validation** — validators call `maestro.token.validate()` with a `revocation_lists` dict populated from their local cache. If the cache is stale, revocation checks may fail to detect recently-revoked tokens.

**What the protocol does NOT define:**
- How validators discover revocation lists
- How often validators refresh revocation state
- Whether revocation propagation is push or pull
- Any centralized revocation registry

Revocation distribution is a deployment concern. The protocol provides the record format; the swarm provides the distribution mechanism.

### 2.5 Token Transfer (Future — v2)

```
maestro.token.transfer(
    token_id: str,
    new_bearer_id: str
) -> dict  # new token with updated bearer_id
```

Bearer transfers token to a new bearer. Requires bearer's signature. Payload may define transfer rules (interpreted by the Venue, not the protocol).

---

## 3. Signing Protocol

### 3.1 Canonical JSON

Before signing, the token is serialized to canonical JSON:

```python
def canonical_json(token_fields: dict) -> str:
    """Serialize token fields for signing: sorted keys, no whitespace."""
    fields = {k: v for k, v in token_fields.items() if k != "signature"}
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))
```

### 3.2 Signature

```python
message_hash = sha256(canonical_json(token_fields))
signature = ed25519_sign(message_hash, issuer_private_key)
```

The signature covers all fields except `signature` itself. The public key is embedded in `issuer_public_key` so verifiers don't need external key resolution.

### 3.3 Verification

```python
message_hash = sha256(canonical_json(token_fields))
valid = ed25519_verify(message_hash, signature, issuer_public_key)
```

The embedded `issuer_public_key` MUST match a known agent in the registry for the token to be trusted — but signature verification itself is self-contained.

---

## 4. Crypto Primitives

From `maestro_crypto.py` (existing):

```python
from maestro_crypto import (
    sign,         # sign(message: str, private_key_hex: str) -> str (hex signature)
    verify,       # verify(message: str, signature_hex: str, public_key_hex: str) -> bool
    hash_string,  # hash_string(input_str: str) -> str (SHA-256 hex)
    hash_concat,  # hash_concat(*parts: str) -> str
)
```

---

## 5. Transport Enforcement

The Maestro relay validates tokens but does not interpret them.

### 5.1 What the Relay Checks

1. Signature validity (Ed25519 verify)
2. Expiry (if set)
3. Revocation status (issuer's revocation list)

### 5.2 What the Relay Does NOT Check

- Issuer identity or trustworthiness
- Payload contents
- Whether the bearer "should" have this token
- Venue-specific rules
- Resource authorization (that's the Venue's job)

The relay is issuer-agnostic. Any agent can issue tokens. Any agent can present tokens. The relay verifies the cryptographic primitives and moves on.

---

## 6. Venue Interpretation Model

Venues define token meaning through two mechanisms:

### 6.1 Issuer Filtering

A Venue decides which issuers it trusts:

```
TaskMaster accepts: issuer == taskmaster
LOCR accepts: issuer == taskmaster || issuer == locr
Plaza accepts: any issuer
```

### 6.2 Payload Convention

A Venue defines what payload structures it recognizes:

```json
// TaskMaster work assignment
{"task_id": "...", "task_type": "web-design", "deadline": "..."}

// LOCR credential attestation
{"credential_uid": "a3k9m2"}

// Plaza contact grant
{"contact": true, "endpoint": "http://...", "nickname": "..."}

// Memory Market dry-cleaning ticket
{"memory_id": "#473", "access": "read"}

// Capability delegation (TaskMaster or any Venue)
{"scope": {"actions": ["bb_read"], "resources": ["board:marketing_board"]}}

// TaskMaster escrow intent
{"escrow_id": 123, "rating": 5, "justification_hash": "0x..."}

// TaskMaster escrow acceptance
{"escrow_id": 123, "accept_intent_hash": "0x..."}
```

Same token primitive. Same relay. Different payload interpretations.

---

## 7. Module Location

```
maestro-sdk/runtime/
├── maestro/
│   ├── __init__.py
│   ├── __main__.py
│   ├── secrets.py
│   └── tokens.py             # NEW: issue, validate, revoke, canonical_json
├── maestro_crypto.py          # Existing — Ed25519 primitives
└── maestro_transport.py       # Existing — token validation at enforcement points
```

`tokens.py` imports from `maestro_crypto.py`. It has zero dependencies on TaskMaster, LOCR, Venues, or any application code. All downstream systems import from `maestro.tokens`.

---

## 8. API Reference

```python
# maestro/tokens.py

def issue_token(
    bearer_id: str,
    payload: dict,
    issuer_id: str,
    issuer_private_key_hex: str,
    issuer_public_key_hex: str,
    expiry: int | None = None,
) -> dict:
    """Issue a new token. Signs with issuer's private key.
    
    Args:
        bearer_id: Agent ID this token is issued to
        payload: Opaque dict — Venue defines its meaning
        issuer_id: Agent ID of the issuer
        issuer_private_key_hex: Ed25519 private key (hex)
        issuer_public_key_hex: Ed25519 public key (hex)
        expiry: Unix timestamp or None for permanent
    
    Returns:
        Signed token dict with all protocol fields + signature
    """
    ...

def validate_token(
    token: dict,
    revocation_lists: dict | None = None,
) -> tuple[bool, str]:
    """Validate a token's cryptographic integrity and liveness.
    
    Checks: signature, expiry, revocation status.
    Does NOT check: payload contents, issuer trustworthiness, bearer authorization.
    
    Args:
        token: Token dict in protocol schema
        revocation_lists: Optional dict of issuer_id → set of revoked token_ids
    
    Returns:
        (valid: bool, reason: str)
    """
    ...

def revoke_token(
    token_id: str,
    issuer_id: str,
    issuer_private_key_hex: str,
) -> dict:
    """Revoke a token. Adds to issuer's revocation list.
    
    Returns:
        Revocation record: {token_id, issuer_id, revoked_at, signature}
    """
    ...

def canonical_json(token_fields: dict) -> str:
    """Serialize token fields for signing: sorted keys, no whitespace.
    
    Excludes the 'signature' field. Used internally by issue_token and validate_token.
    """
    ...

def transfer_token(
    token: dict,
    new_bearer_id: str,
    bearer_private_key_hex: str,
) -> dict:
    """Transfer a token to a new bearer. (Future — v2)
    
    Returns a new token with updated bearer_id, preserving original issuer + payload.
    """
    ...
```

---

## 9. Integration Test Suite

### Test 1: Issue/Validate Round-Trip
- Issue token (lexicon → proteus, payload: `{"access": "read"}`)
- Validate → passes
- Tamper with payload → validation fails

### Test 2: Expiry Enforcement
- Issue token with expiry = now + 1s
- Sleep 2s
- Validate → fails with "expired"

### Test 3: Revocation
- Issue token
- Revoke token
- Validate → fails with "revoked"

### Test 4: Signature Tampering
- Issue token
- Modify `bearer_id` in token
- Validate → fails with "invalid_signature"

### Test 5: Payload Opacity
- Issue token with payload: `{"custom_venue_field": "anything"}`
- Validate → passes (payload is opaque to protocol)
- No validation error from unrecognized payload fields

### Test 6: Bearer Mismatch (Venue-Level)
- Validate token where `bearer_id != caller_id`
- Protocol validation PASSES (bearer mismatch is a Venue concern)
- Document that Venues must check `token["bearer_id"]` against the presenting agent

---

## 10. Key Files

| File | Action | Phase |
|------|--------|-------|
| `maestro-sdk/runtime/maestro/tokens.py` | **CREATE** — issue, validate, revoke, canonical_json, transfer (stub) | 1 |
| `maestro-sdk/runtime/maestro_crypto.py` | Existing — Ed25519 primitives (no changes) | — |
| `maestro-sdk/specs/SPEC_MAESTRO_TOKEN_PRIMITIVE.md` | **CREATE** — this document | 1 |
| `maestro-sdk/tests/test_token_primitive.py` | **CREATE** — integration tests | 1 |
| `maestro-sdk/specs/SPEC_MAESTRO_DELEGATION_TOKENS.md` | **ARCHIVE** — replaced by this spec | — |

---

## 11. Backward Compatibility

The existing `SPEC_MAESTRO_DELEGATION_TOKENS.md` is **superseded**. It embedded `scope`, `actions`, `resources`, `venues`, `allow_delegation`, and `heartbeat_required` into the token schema — violating the ADR principle that these are payload-level concerns.

**Migration:** Any implementation based on the old spec must:
1. Move `scope` → `payload.scope` (Venue-defined convention)
2. Drop `heartbeat_required` and `revocation_endpoint` from protocol fields
3. Drop `delegation_chain` from protocol fields (chain tracking is a payload-level convention)
4. Rename `delegator_id` → `issuer_id`, `delegate_id` → `bearer_id` (generalized naming)

The capability delegation use case is still fully supported — it just lives in the payload, not the protocol.

---

## 12. Success Criteria

1. `maestro/tokens.py` can issue, validate, and revoke tokens using Ed25519 signatures
2. Token validation rejects: bad signatures, expired tokens, revoked tokens
3. Token validation is neutral: passes tokens with any payload structure without interpretation
4. TaskMaster can `from maestro.tokens import issue_token, validate_token` with zero changes
5. LOCR can define credential attestation tokens using the same primitive
6. No `type`, `scope`, or `actions` field exists at the protocol level
7. ADR_MAESTRO_TOKEN_PRIMITIVE.md and this spec are consistent
