# ADR-015 — Remove Communication Policy from the Transport Layer

**Status:** Incorporated into ADR-017 (Authority Originates with Actors) — the capability model already implements this
**Date:** 2026-07-06
**Author:** Sentinel (with Jesse)
**Supersedes:** None directly. Refactors the DM token system established in ADR-003, ADR-004, ADR-008.

---

## 1. Observation

The transport layer (`maestro_transport.py`) currently enforces DM permission policy via `_check_dm_policy`. On every `direct` or `directive` message, the transport asks:

> "Should this interaction occur?"

This is a policy question. Per the composition model (`maestro-composition-model.md` §2.3, §4.3):

> "The nucleus never makes policy decisions. It never asks 'should this interaction occur?' Policy pushes upward into Environments."

The transport is Grammar. Grammar routes. Grammar verifies identity. Grammar does not gate communication based on who is allowed to talk to whom.

### Evidence

- `_check_dm_policy` (line 892) lives in `MaestroTransport`, the base transport class
- It is gated by `dm_policy.enabled` in per-agent configs — a boolean that has drifted across the fleet (stormtrooper: false, 12 non-officer agents: false)
- The DM token system centralizes authority in Lexicon as sole issuer, contradicting the "edges are fundamental" model
- Configuration drift has already occurred: tokens were fixed in June but `dm_policy.enabled` was never re-enabled on all agents (mitigation drift documented in songbird.jsonl, 2026-06-19)

### Current Flow (broken)

```
Transport
    ↓
Identity verification
    ↓
Routing
    ↓
DM Policy ← "Should this interaction occur?" ← POLICY LEAK
    ↓
Delivery
```

---

## 2. Root Cause

Communication policy was embedded in the transport layer during early development when the distinction between Grammar and Policy was not yet formalized. The composition model now clearly separates these concerns, but the transport has not been refactored to match.

The DM token system also inherited a centralized-issuer model (Lexicon as sole token authority) that contradicts the peer-to-peer relationship model the architecture has since adopted.

---

## 3. Proposed Design

### 3.1 Remove DM Policy from Transport

The transport layer returns to pure Grammar:

```
Transport
    ↓
Identity verification
    ↓
Routing
    ↓
Delivery
```

The transport no longer asks "should this interaction occur?" It only asks "is this packet well-formed and authentic?" — exactly as TCP doesn't ask whether you should open a socket.

### 3.2 DM Becomes a Capability

DM is a communication Capability, not a transport policy:

```
Grammar (transport)
    ↓
Identity
    ↓
Routing
    ↓
Capabilities
    DM
    Broadcast
    Pipeline
    ↓
Policies
    Personal (agent-issued tokens)
    Venue (environment-issued tokens)
    ↓
Interaction
```

**Outside any Venue:** Bob may accept DMs based on Bob-issued tokens. Bob controls his own contacts.

**Inside a Venue:** The Venue may override with relay tokens. Bob's personal DM tokens become irrelevant — the environment supersedes them.

### 3.3 Each Agent Issues Their Own Tokens

Permission is an edge, not a registry entry:

```
Alice ─────► Bob
```

That edge exists because **Bob created it** — not because Lexicon or any central authority says so. Bob issues a "Bob-DM" token to Alice. When Alice messages Bob, she presents the token. Bob verifies his own signature.

This mirrors SSH: if you want into my server, I add your public key to `authorized_keys`. You don't ask GitHub. You don't ask DNS. I decide.

### 3.4 Design Principle

> **Communication permissions are owned by the recipient, not granted by the network.**

Maestro doesn't decide who can talk to whom. Agents do. Venues may temporarily constrain those relationships, but the substrate itself remains neutral.

---

## 4. Implementation

### Phase 1: Remove DM Policy from Transport

1. Remove `_check_dm_policy` from `maestro_transport.py`
2. Remove `dm_policy` config block from all agent configs
3. Remove the DM gate at lines 1012-1022
4. Remove `TOKENS_AVAILABLE`, `_validate_token`, `_dm_token_dir`, `_dm_issuer_pubkey`, `_dm_venue` from transport init

### Phase 2: Build DM Capability

1. Create `maestro/capabilities/dm.py` — a DM Capability module
2. Each agent can issue DM tokens: `dm.issue_token(bearer_id="proteus", ttl_hours=720)`
3. Each agent can verify presented tokens: `dm.verify_token(token, expected_bearer="proteus")`
4. Token format: signed by the issuer (recipient), presented by the bearer (sender)

### Phase 3: Venue Integration

1. Venues can issue their own pipeline/relay tokens
2. When a Venue token is present, personal DM tokens are superseded
3. The relay evaluator (ADR-004b, ADR-006) validates Venue tokens at each hop

---

## 5. What This Eliminates

| Problem | How It's Eliminated |
|---|---|
| `dm_policy.enabled` configuration drift | The concept no longer exists in transport |
| Central issuer bottleneck (Lexicon) | Each agent is its own issuer |
| "Mitigation drift" (tokens fixed, gate still off) | No gate to drift |
| Transport making policy decisions | Transport returns to pure Grammar |
| Confusion about who controls permissions | Recipient controls their own edges |

---

## 6. Boundary Impact

- **Transport layer:** Loses ~50 lines of policy code. Gains clarity.
- **DM token system:** Moves from transport to Capability layer. Redesigned from centralized to peer-to-peer.
- **Venues:** Gain the ability to issue their own communication tokens, superseding personal DM tokens within the Venue context.
- **Existing ADRs:** ADR-003 (modular rebuild) already anticipated this — the DM Enforcer (M02) was always intended as a separate module. ADR-004b (relay architecture) already describes Venue-level token validation. This ADR aligns implementation with those designs.

---

## 7. Recurrence

This eliminates an entire class of problems:

- Configuration drift in communication policy
- Central authority bottlenecks for peer-to-peer relationships
- Policy leaking into the Grammar layer
- "Who controls this permission?" ambiguity

---

## 8. Open Questions

1. **Token format:** Should DM tokens use the existing Ed25519 token format from `maestro/tokens.py`, or a simplified format?
2. **Discovery:** How does Alice discover that Bob is willing to accept DMs? Does Bob publish a capability endpoint?
3. **Migration:** What happens to existing Lexicon-issued tokens during the transition? Grace period where both systems coexist?
4. **Venue token precedence:** How does the relay evaluator determine whether a Venue token supersedes a personal DM token? Is it simply "if Venue context exists, use Venue tokens"?
