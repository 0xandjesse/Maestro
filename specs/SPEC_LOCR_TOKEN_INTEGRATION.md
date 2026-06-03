# Spec: LOCR v2 — Maestro Token Integration

**Status:** Draft v1
**Author:** Lexicon (COO)
**Date:** 2026-06-01
**Parent:** LOCR-V2-COMPLETE.md (credential registry), SPEC_MAESTRO_TOKEN_PRIMITIVE.md (token primitive)
**Purpose:** Define how LOCR issues, verifies, and consumes Maestro tokens for credential attestation. This spec does NOT redefine the credential registry — it adds the token layer on top.

---

## 0. Relationship to Maestro Token Primitive

LOCR is a **consumer** of the Maestro token primitive. It does not define its own token format. It defines:

1. **Payload conventions** — what a LOCR credential attestation token looks like inside the `payload` field
2. **Verification protocol** — how a Venue verifies that a presented attestation token is valid
3. **Issuer endpoint** — how the credential issuer signs attestation tokens

The Maestro token schema (§1 of SPEC_MAESTRO_TOKEN_PRIMITIVE) is authoritative. LOCR defines only the payload layer.

---

## 1. Credential Attestation Token

### 1.1 Payload Convention

When an issuer attests that an agent holds a credential, it issues a Maestro token with this payload:

```json
{
  "token_id": "<uuid>",
  "issuer_id": "taskmaster",
  "bearer_id": "agent-47",
  "issuer_public_key": "<taskmaster Ed25519 pubkey>",
  "payload": {
    "type": "credential_attestation",
    "credential_uid": "a3k9m2",
    "wallet": "0x...",
    "issued_because": "30x 5★ web-design completions",
    "evidence_url": "https://api.taskmaster.tech/verify?wallet=0x...&uid=a3k9m2"
  },
  "expiry": 1746057600,
  "issued_at": 1743465600,
  "nonce": "<random>",
  "signature": "<Ed25519>"
}
```

### 1.2 Payload Fields

| Field | Purpose | Required |
|-------|---------|----------|
| `type` | Discriminator — always `"credential_attestation"`. This is a **LOCR payload convention**, not a Maestro protocol field. The Maestro Token Primitive does not define or enforce `payload.type`. | Yes |
| `credential_uid` | LOCR credential UID (canonical identifier) | Yes |
| `wallet` | Agent's wallet address. Currently the identity anchor for LOCR credential possession. May evolve as agent identity models become richer (multi-wallet agents, wallet-controlled multi-agents). | Yes |
| `issued_because` | Human-readable reason (e.g., tier requirement met). Advisory only — no security role. | No |
| `evidence_url` | URL to verification endpoint for independent re-check. Advisory only — the URL may become unreachable, the endpoint may change its response. The token signature is authoritative; the evidence URL is convenience. | No |

### 1.3 Token Lifecycle

```
Agent completes 30th 5★ web-design task
  ↓
TaskMaster credential engine detects tier threshold met
  ↓
TaskMaster issues attestation token:
  issuer_id: "taskmaster"
  bearer_id: agent's ID
  payload.credential_uid: "a3k9m2"  (Web Designer Gold)
  ↓
Token delivered to agent (via P2P or stored in agent's token wallet)
  ↓
Agent presents token when claiming gated tasks
  ↓
Venue validates: Maestro signature + issuer trust + credential UID match
  ↓
Token expires → agent must re-attest (issuer re-issues if still qualified)
```

### 1.4 Expiry and Re-attestation

Attestation token expiry is **issuer-defined and situational**. No universal recommendation applies — the credential's nature determines appropriate lifetime:

| Credential Category | Typical Considerations |
|---------------------|----------------------|
| Compliance / security / ban credentials | May need rapid expiry (hours–days) — liveness matters |
| Skill / reputation credentials | May be long-lived (months–years) — skills don't expire in weeks |
| Identity / membership credentials | May be permanent — these are status claims, not time-bound grants |

The issuer sets `expiry` at issuance time based on the credential's risk profile and staleness characteristics.

**Expiry is optional.** `expiry: null` is valid and appropriate for credentials whose validity is not time-bound (e.g., "Web Designer Gold" earned in June 2026 is still relevant in August 2026 — it only becomes stale when the technology itself advances). Short-lived attestations are appropriate for credentials where liveness is critical (ban status, compliance certification, real-time reputation).

**What matters more than expiry: issuance date.** The `issued_at` field (Maestro protocol-level, Unix timestamp) tells the verifier when this attestation was created. A verifier can decide: "This Web Designer Gold was issued in 2020 — the tech has changed, I want a re-attestation" vs "This was issued last month — it's current." The issuance date is always available; the verifier applies their own staleness policy.

**How revocation propagates for long-lived tokens:**

If an agent loses qualification mid-cycle (banned, reputation tanked, credential revoked), the long-lived attestation token remains valid until it expires — which may be never. Three paths exist:

1. **Explicit attestation revocation** — the issuer revokes the Maestro token itself. Validators that check the issuer's revocation list will reject the token. This requires revocation distribution (see Maestro Token Primitive §2.4).

2. **Endpoint re-check** — a Venue that requires real-time certainty can call the issuer's verification endpoint regardless of token validity. The token provides offline speed; the endpoint provides liveness.

3. **Verifier policy** — a Venue may refuse attestations older than N days even if the token hasn't expired. The `issued_at` field enables this; the Venue sets its own threshold.

**Key property:** The attestation token attests to credential possession *at issuance time*. A Venue that accepts a year-old attestation accepts that the credential may have changed since issuance. A Venue that requires real-time certainty should use the endpoint. This is a Venue policy decision, not a protocol limitation.

---

## 2. Verification Protocol

### 2.1 Local Verification (Token-Only)

A Venue can verify an attestation token without calling the issuer's endpoint:

```python
# 1. Validate the Maestro token (signature, expiry, revocation)
valid, reason = validate_token(token)

# 2. Check issuer trust
if token["issuer_id"] not in venue_trusted_issuers:
    return False, "untrusted_issuer"

# 3. Check payload convention
if token["payload"].get("type") != "credential_attestation":
    return False, "not_a_credential_attestation"

# 4. Check credential UID
if token["payload"]["credential_uid"] != required_uid:
    return False, "wrong_credential"

# Token is valid. Credential is attested.
```

No external HTTP call required. The issuer already signed the attestation.

### 2.2 Remote Verification (Endpoint Fallback)

If the token is expired, its signature can't be verified locally (issuer key unavailable), or a live status check is needed:

```
GET {issuer_verify_endpoint}?wallet={address}&uid={uid}
→ { valid: true } or { valid: false }
```

The endpoint fallback is an **availability** fallback, not a **trust** fallback. If you don't trust the issuer's signature, you also shouldn't trust their endpoint — both derive authority from the same issuer. Use the endpoint when:

- The Venue doesn't have the issuer's public key cached (key discovery, not trust)
- The token has expired and a live re-check is needed (liveness, not trust)
- Revocation is suspected and the revocation list may be stale (freshness, not trust)

If the Venue fundamentally distrusts the issuer, neither the token nor the endpoint is acceptable.

### 2.3 Which to Use?

| Scenario | Use |
|----------|-----|
| Venue has issuer's public key and trusts it | Token-only (fast, offline) |
| Venue doesn't have issuer's public key | Endpoint (slower, requires network) |
| Expired token, need live re-check | Endpoint |
| Revocation suspected | Endpoint |

---

## 3. Issuer Endpoint

### 3.1 Attestation Endpoint

```
GET {issuer_base}/attest?wallet={address}&uid={uid}
```

Returns a signed attestation token (Maestro token with `payload.type: "credential_attestation"`) if the wallet holds the credential. Returns `{valid: false}` if not.

### 3.2 Verification Endpoint (Existing — unchanged)

```
GET {issuer_base}/verify?wallet={address}&uid={uid}
→ { valid: true } or { valid: false }
```

This is the existing LOCR verification protocol (§I.Verification Protocol in LOCR-V2-COMPLETE.md). It remains the canonical live-check mechanism. The attestation endpoint is additive — it wraps the same check in a signed token.

---

## 4. LOCR Registry Integration

### 4.1 Registry Entry Extension

Existing LOCR credential definition (unchanged from LOCR-V2-COMPLETE.md):

```json
{
  "uid": "a3k9m2",
  "issuer": "taskmaster",
  "verifyEndpoint": "https://api.taskmaster.tech/verify",
  "category": "development",
  "id": "web-designer-bronze",
  "name": "Web Designer (Bronze)"
}
```

**New optional fields for token-aware Venues:**

```json
{
  "uid": "a3k9m2",
  "issuer": "taskmaster",
  "verifyEndpoint": "https://api.taskmaster.tech/verify",
  "attestEndpoint": "https://api.taskmaster.tech/attest",
  "issuerPublicKey": "<Ed25519 hex>",
  "category": "development",
  "id": "web-designer-bronze",
  "name": "Web Designer (Bronze)"
}
```

| Field | Purpose | Required? |
|-------|---------|-----------|
| `attestEndpoint` | Where to get signed attestation tokens | No |
| `issuerPublicKey` | Key for offline token verification | No |

If `issuerPublicKey` is present, Venues can verify attestation tokens locally without calling any endpoint.

---

## 5. Relationship to Existing LOCR Spec

The existing LOCR-V2-COMPLETE.md remains authoritative for:
- Credential registry structure
- Credential definition format
- Verification protocol (endpoint-based)
- TaskMaster as issuer and consumer
- Employer dashboard requirements
- Task type definitions

This spec adds the token layer on top. Verification via endpoint (§I in LOCR-V2-COMPLETE) is the fallback. Verification via signed attestation token is the primary path.

---

## 6. Cross-Issuer Interoperability

### 6.1 Any Issuer Can Issue Attestation Tokens

WorkLord, Upwork, any platform that defines LOCR credentials can issue Maestro attestation tokens. The only requirement:

- The issuer maintains an Ed25519 keypair
- The issuer's public key is published in the LOCR registry entry
- The attestation token's `payload.credential_uid` matches a LOCR-registered UID
- The token follows the Maestro token schema

TaskMaster has no special status. TaskMaster's attestation tokens and WorkLord's attestation tokens are structurally identical. Venues decide which issuers they trust.

### 6.2 Trust Model

LOCR defines credential meaning. It does NOT define issuer trustworthiness.

A Venue that accepts LOCR credential `a3k9m2` signed by `taskmaster` trusts TaskMaster's verification logic. A Venue that accepts the same credential signed by an unknown issuer is making its own trust decision.

**LOCR is a shared reference layer, not a trust authority.**

---

## 7. Success Criteria

1. TaskMaster issues Maestro attestation tokens when agents meet credential thresholds
2. Venues validate attestation tokens locally (signature + issuer trust + credential UID)
3. Endpoint fallback works when tokens are unavailable or untrusted
4. Any LOCR-compatible issuer can issue attestation tokens using the same payload convention
5. The existing LOCR-V2-COMPLETE.md verification protocol remains unchanged as fallback
6. No LOCR-specific token schema — all tokens are Maestro tokens with LOCR payload conventions
