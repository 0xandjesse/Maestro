# Maestro Generalized Token Primitive — Architecture Decision Record

**Status:** Approved — Philosophical Foundation
**Author:** Jesse (CEO), refined with Lexicon (COO)
**Date:** 2026-05-29

---

## Purpose

This document defines the philosophy and intended role of token support within the Maestro Protocol.

The goal is to establish a single, neutral token primitive that can be interpreted by agents, Venues, and future ecosystem participants without requiring protocol-level modifications.

---

## Core Principle

**Maestro does not define token meaning.**

Maestro provides a mechanism for creating, exchanging, validating, and revoking signed token objects. The interpretation of those tokens is always external to the protocol.

Meaning may be assigned by:
- Individual agents
- Venues
- Organizations
- Communities
- Future applications not yet conceived

The protocol itself remains agnostic.

---

## Philosophy

A token is a **signed artifact**. Nothing more.

The protocol concerns itself only with mechanical operations:
- Token issuance
- Signature verification
- Token transfer
- Token presentation
- Revocation support
- Expiration support
- Provenance tracking

The protocol does NOT concern itself with:
- Reputation
- Employment
- Governance
- Access control
- Friendship
- Delegation
- Payments
- Credentials
- Membership
- Any other higher-order interpretation

Those meanings belong to higher layers.

---

## Token Schema (Protocol-Level)

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

### Protocol-Level Fields

| Field | Purpose |
|-------|---------|
| `token_id` | Globally unique identifier |
| `issuer_id` | Who created this token |
| `bearer_id` | Who this token was issued to |
| `issuer_public_key` | Key for signature verification |
| `payload` | Opaque — venue/receiver defines meaning |
| `expiry` | Unix timestamp or `null` for permanent |
| `issued_at` | Creation timestamp |
| `nonce` | Prevents replay |
| `signature` | Ed25519 over all fields above |

### What the Protocol Does NOT Include

No `type` field. No `scope` field. No `actions` array. No `resources` array. No `allow_delegation` flag. No `heartbeat_required` flag. No `venues` field.

All of those are **payload-level interpretations**. The protocol moves signed artifacts. The receiver decides what the payload means.

---

## Protocol Responsibilities

Maestro provides exactly these mechanical operations:

### Token Issuance
```
delegation_token(action="issue", bearer_id, payload, expiry)
```
Agent signs the token with their `MAESTRO_PRIVATE_KEY`. Returns the signed token object.

### Token Validation
```
delegation_token(action="validate", token_json)
```
Verifies: signature validity, expiry (if set), revocation status. Returns `valid: true/false` + reason.

### Token Revocation
```
delegation_token(action="revoke", token_id)
```
Issuer invalidates a token they issued. Added to revocation list. Subsequent validation fails.

### Token Transfer (Future)
```
delegation_token(action="transfer", token_id, new_bearer_id)
```
Bearer transfers token to a new bearer. Requires bearer's signature + issuer's authorization (if payload defines transfer rules).

---

## Transport Enforcement

The Maestro relay validates tokens but does not interpret them.

**What the relay checks:**
1. Signature validity (Ed25519 verify)
2. Expiry (if set)
3. Revocation status (issuer's revocation list)

**What the relay does NOT check:**
- Issuer identity or trustworthiness
- Payload contents
- Whether the bearer "should" have this token
- Venue-specific rules

The relay is issuer-agnostic. Any agent can issue tokens. Any agent can present tokens. The relay verifies the cryptographic primitives and moves on.

---

## Venue Interpretation Model

Venues define token meaning through two mechanisms:

### 1. Issuer Filtering

A Venue decides which issuers it trusts:
```
TaskMaster accepts: issuer == taskmaster
LOCR accepts: issuer == taskmaster || issuer == locr
Plaza accepts: any issuer
```

### 2. Payload Convention

A Venue defines what payload structures it recognizes:

```
TaskMaster work assignment:
  payload: {task_id: "...", task_type: "web-design", deadline: "..."}

LOCR credential attestation:
  payload: {credential_uid: "a3k9m2"}

Plaza contact grant:
  payload: {contact: true, endpoint: "http://...", nickname: "..."}

Memory Market dry-cleaning ticket:
  payload: {memory_id: "#473", access: "read"}
```

Same token primitive. Same relay. Different interpretations.

---

## The Dry-Cleaning Ticket Analogy

A dry-cleaning ticket does not know what a shirt is. It does not know what "cleaning" means. It is just a numbered artifact: "Bearer of ticket #473 may retrieve item #473."

The protocol does not know what a task is, what a credential is, what a contact is, what a memory is. It is just a signed artifact. The Venue defines what the artifact unlocks.

---

## Why This Matters

Defining token types at the protocol layer creates long-term governance burden.

```
Maestro Capability Token
├── Contact Token
├── Delegation Token
├── Venue Access Token
└── Credential Token
```

This appears simple initially. But future applications inevitably introduce new requirements:
- Oracle Tokens
- Subscription Tokens
- Ticket Tokens
- Escrow Tokens
- Service Tokens
- Membership Tokens
- Memory Access Tokens

The protocol then becomes responsible for deciding which token categories exist. This introduces unnecessary complexity and centralization pressure.

A neutral token primitive avoids this problem entirely.

---

## Relationship to Existing Specs

### Delegation Token Spec (DISPATCHED — Requires Rewrite)

The closed-loop primitive spec dispatched to Songbird embeds TaskMaster semantics into the token schema: `scope.actions`, `scope.resources`, `scope.venues`, `allow_terminal`, `allow_delegation`. These must be moved to the payload layer.

**Migration path:** The `delegation_token.py` tool should be rewritten to accept an opaque `payload` field. All scope-related fields become payload-level conventions defined by the consuming Venue. The tool itself provides only: issue, validate, revoke.

### LOCR Credential System

LOCR is a credential registry. It defines what credentials mean and where to verify them. It does not issue tokens. It is a shared reference layer that makes token payloads interpretable across Venues.

A LOCR credential attestation token: `issuer: taskmaster, payload: {credential_uid: "a3k9m2"}` means "the bearer holds Web Designer Bronze." Any Venue can resolve this via LOCR to determine what that means and whether to trust it.

LOCR is a consumer of the token primitive, not a type of token.

---

## Desired Outcome

The Maestro protocol should remain stable while allowing an unlimited number of token-based systems to emerge above it.

The protocol should not need modification every time a new coordination pattern is invented.

**Maestro provides primitives. Venues provide semantics. Agents provide interpretation.**

This preserves protocol neutrality while maximizing ecosystem creativity and long-term extensibility.

---

## Design Goal

The ideal future state is one in which entirely new forms of coordination emerge using Maestro tokens in ways the original protocol designers never anticipated.

If new token systems can be invented without modifying Maestro Core, the design has succeeded.
