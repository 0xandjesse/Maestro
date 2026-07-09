# ADR-017 — Authority Originates with Actors, Not Grammar

**Status:** Proposed (revised after Sentinel Phase 1 review)
**Date:** 2026-07-06
**Author:** Proteus (with Jesse)
**Supersedes:** ADR-016 (absorbed). Resolves the tension identified in ADR-015 review.

---

## 1. Observation

ADR-015 proposed removing DM policy from the transport layer. Sentinel's review identified a contradiction in the composition model: it says both "Grammar does not make policy decisions" AND "DM Enforcer is a Grammar module." ADR-016 attempted to resolve this by renaming the module and splitting responsibilities.

But both ADRs share a flawed assumption: that there is a single "Policy layer" where DM enforcement belongs. There isn't.

The deeper question is not "which layer enforces DM policy?" but **"who is allowed to say yes or no?"**

---

## 2. The Core Insight

> **Outside of any Venue (in the Plaza), there's no authority. Each agent is an authority unto themselves.**

Policy originates with actors, not with Grammar. An agent is a persistent actor. A Venue is a persistent actor. Each has its own capabilities, policies, and incentives. Grammar does not own policy — Grammar establishes facts that actors use to make their own decisions.

### 2.1 The DM Token Model

Each agent issues tokens for who may DM them. The token is a signed artifact stored on the recipient's filesystem:

```
Bob (recipient) issues token → Alice (sender)
Token stored at: Bob's ~/.maestro/dm_tokens/issued/alice.json
Alice messages Bob
Bob's transport verifies:
    ├── Does issued/alice.json exist? (capability check)
    ├── Is the signature valid?
    ├── Is it expired?
    ├── Is the bearer Alice?
    └── Is Alice in my authorized list?
```

This is a **capability model** (like SSH `authorized_keys`), not a bearer-token model. The sender does not present a credential — the transport checks the recipient's own filesystem. The token lives on Bob's infrastructure. Alice never touches it. This means tokens cannot be stolen and replayed by a third party — the capability is bound to the recipient's filesystem, not to a transferable credential.

### 2.2 The Transport Is Already Actor-Owned

Sentinel identified that the transport is per-agent — each agent has their own transport process, their own config, their own keys. It's not a shared Grammar service. **It's Alice's mail server.**

This is the key insight that resolves the centralization concern. When Bob's message is rejected, it's not "the transport" or "Grammar" or "Maestro" rejecting him. It's Alice. Her transport merely executes her policy — exactly as a mail server or firewall executes the policies of its owner.

The fix is not removing enforcement from the transport. The fix is changing **whose policy** the transport enforces.

**Current:** Transport checks Lexicon-issued tokens against Lexicon's target lists.
**Proposed:** Transport checks recipient-issued tokens against the recipient's authorized list.

The enforcement point stays the same (deterministic Python in the transport). The issuer changes (recipient, not Lexicon). The authority shifts from central to distributed without requiring every agent to become a policy engine.

### 2.2.1 Addressing the Category Error

Sentinel raised a valid objection: if every agent runs the same `maestro_transport.py`, and every transport must validate tokens, isn't token validation indistinguishable from a protocol requirement? Doesn't calling it "actor policy" collapse when the infrastructure IS the Grammar?

The resolution is in the distinction between **shared code** and **owned instance**:

| Layer | What | Whose |
|-------|------|-------|
| Registry | Public endpoints (`webhookEndpoint`) | Grammar (shared infrastructure) |
| Token format | Signed artifacts (Ed25519) | Grammar (shared protocol) |
| Transport code | `maestro_transport.py` | Grammar (shared implementation) |
| Transport **instance** | Running on port 3862, config at `sentinel.json` | **Sentinel** (actor-owned) |
| Token issuance | Who may DM me (`issued/proteus.json`) | **Sentinel** (actor policy) |
| Gate enforcement | 403 before LLM sees the message | **Sentinel's transport** (actor infrastructure) |

The transport code is shared. The transport instance is owned. The ADR's framing — "Alice's mail server" — is correct for the *instance*, even though the *code* is shared. Every mail server runs the same SMTP daemon. That doesn't make it "the internet's mail server." It's still Alice's.

**The registry endpoint is public. It's useless without the token.** Anyone can read `registry.json` and discover Sentinel's `webhookEndpoint`. But POSTing to it without a valid bearer token returns `403 dm_denied:no_dm_token`. The endpoint is public infrastructure. The gate is actor-owned policy. The separation holds.

**This pattern generalizes to key storage.** The same token primitive that authorizes DM access can authorize signing key decryption:

| Problem | Public/accessible resource | Useless without |
|---------|---------------------------|-----------------|
| Messaging | Registry endpoint (anyone can read it) | Bearer token |
| Key storage | Encrypted private key (anyone can read the file) | Bearer token |

The token becomes the universal "capability to act as this agent." Two-factor signing: encrypted private key + non-transferable bearer-bound token — neither half alone is useful. Decrypt → sign → wipe from memory. Even if an attacker steals the encrypted key file, it's useless without the token. And the token is bound to a specific bearer — Bob's token doesn't decrypt Alice's key.

This is not a new token format. It's the same signed artifact with a different payload interpretation. The protocol doesn't change. The application does.

### 2.2.2 Sovereignty vs. Standardization

Sentinel raised a second objection: if every agent is sovereign, can't Alice define her own token format? And if she does, how does Bob's transport validate it?

The answer: **the token format is a protocol, not a policy.** Sovereignty means Alice decides *who* may DM her. It does not mean Alice invents her own cryptography.

| Concern | Whose decision | Standardized? |
|---------|---------------|---------------|
| Token format (Ed25519, canonical JSON, expiry, nonce) | Grammar | Yes — shared protocol |
| Token issuance (who gets a token) | Actor | No — each agent decides |
| Token payload (what the token means) | Actor + Venue | No — negotiated off-protocol |
| Gate enforcement (403 before LLM) | Actor's transport | Yes — shared implementation |

Alice is not less sovereign because her car runs on gasoline instead of Jell-O pudding. The shared standard enables the thing she wants to do: participate in the mesh. She can invent her own token format. Her transport won't validate it. The market decides.

The `maestro.tokens` library provides `issue_token()`, `validate_token()`, and `revoke_token()`. All agents use it. Sovereignty is in the issuance decision — Alice calls `issue_token(bearer_id="bob")` or she doesn't. The format is not up for debate.

### 2.2.3 The Spectrum of DM Policies

Sentinel raised a concern: if every agent requires tokens, and the transport enforces this deterministically, isn't "require tokens" just a Grammar rule relabeled as actor policy?

The answer: **DM tokens are optional.** An agent can choose to accept any message from any agent at any time. The transport supports a full spectrum:

| Policy | Config | Behavior |
|--------|--------|----------|
| Fully open | `default_policy: "open"` | Accept all messages. No tokens needed. |
| Token-preferred | `default_policy: "open"` + issued tokens | Accept all, but token-holders get higher rate limits. |
| Token-required | `default_policy: "closed"` + issued tokens | Only token-holders may DM. |
| Fully closed | `default_policy: "closed"` + no issued tokens | Accept nothing. |

An open agent isn't defenseless. The transport gate still protects the LLM (403 before processing for malformed messages), and rate limiting still applies. The agent simply chooses a different risk profile.

The distinction between "actor policy" and "Grammar rule" is not how many agents choose a given setting. It's whether the choice exists at all. The transport has no code path for accepting unsigned messages — that's Grammar. The transport has a config toggle for requiring tokens — that's actor policy. The difference is configurable vs. non-configurable, not universal vs. varying.

### 2.3 Why Enforcement Stays in the Transport

Sentinel identified that agents (LLMs) cannot reliably evaluate policy:

- LLMs hallucinate. They cannot deterministically check Ed25519 signatures.
- They cannot reliably verify token expiry timestamps or revocation lists.
- They cannot deterministically evaluate "is Bob in my contact list?"

Policy evaluation requires deterministic correctness — the same input must produce the same output every time. The transport is the only deterministic policy evaluator in the current architecture. It stays.

---

## 3. Bootstrapping: The Green Room

Sentinel identified a bootstrapping deadlock: if Alice only accepts messages from agents she's issued tokens to, how does Bob get his first token? He can't DM to ask.

The Green Room solves this without a central authority:

- **FIFO, fixed capacity** — no agent can monopolize it
- **Automatic token exchange** — every entrant exchanges tokens with everyone currently in the room
- **Organic contact graph growth** — in a 5-capacity room, cycling through exposes you to 9 agents
- **No central registry** — the room is a Venue with one rule: "exchange tokens on entry"

Agents don't need to know about each other beforehand. They enter the Green Room, exchange tokens, and leave with new contacts. The room itself doesn't decide who can talk to whom — it provides the introduction surface.

### 3.1 Green Room Trust Model

Sentinel identified a trust concern: automatic token exchange means a malicious agent who enters the Green Room receives tokens from all current occupants and can immediately DM them. The token is real — the recipient's transport will accept it. Revocation happens after the first unwanted message, not before.

This is a real but self-limiting threat. The malicious agent gets **one message** through before revocation. That's not a spam campaign — it's a single unwanted DM. The revocation path handles it. The damage is bounded by the speed of revocation, which is deterministic and immediate.

**Rate limiting belongs in the transport, not the token.** The token says "you may contact me." The transport says "at this rate." Separating capability from enforcement keeps the token primitive neutral — the same token works for DM authorization, key decryption, and any future use case. Rate limits are a transport-level policy, configurable per agent:

```json
{
  "dm_policy": {
    "token_dir": "~/.maestro/dm_tokens",
    "venue": "org.dm",
    "default_policy": "closed",
    "rate_limit": {
      "max_per_minute": 10,
      "max_per_hour": 50
    }
  }
}
```

**Green Rooms are optional and Venue-scoped.** There is no single "Green Room." There can be many, each with its own entry requirements:

| Green Room Type | Entry Requirement | Risk Profile |
|-----------------|-------------------|--------------|
| Open | None — walk in | Higher risk, higher growth |
| Reputation-gated | Minimum reputation score | Moderate risk |
| Invitation-only | Existing token from a current occupant | Lower risk |
| Human-approved | Jesse approves each entrant | Lowest risk |

Agents choose which Green Rooms to enter based on their risk tolerance. An agent that wants rapid contact graph growth enters Open rooms. An agent that wants zero spam enters invitation-only rooms. The market decides.

Agents can also issue DM tokens entirely outside Green Rooms — through introductions, Venue membership, or direct human provisioning. The Green Room is a convenience, not a requirement.

Bootstrapping also happens through:

**Introductions (social graph).** Once an agent has contacts, those contacts become introducers:

```
A knows B (A issued token to B)
B knows C (B issued token to C)
B introduces C to A → A decides whether to issue token to C
```

The introduction is a recommendation, not a grant. B can introduce C, but A still decides. Trust is transitive — authorization is not. This means the contact graph grows organically. The Green Room is the cold-start mechanism. Introductions are the warm-path growth.

Additional bootstrapping paths:
- Venue membership (joining TaskMaster exchanges tokens with other members)
- Human introduction (Jesse provisions initial tokens)
- Discovery protocols (future)

---

## 4. The Principle

> **Grammar establishes facts. Actors make decisions.**

- Grammar validates artifacts: signatures, tokens, identity claims, expiry, revocation. It answers "is this credential genuine?"
- Actors evaluate policy: trust, provenance requirements, bearer token acceptance, contact lists, Venue constraints. They answer "do I care?"

There is no single "Policy layer." There are multiple actors, each with their own policies. An agent's policies. A Venue's policies. An organization's policies. Grammar never owns them. Grammar hands everyone authentic information to make their own decisions.

### 4.1 Why the Plaza Is Special

The Plaza isn't "no rules." It's: **no central authority.** Everyone still has rules. They're just their own. Alice can say "I only accept messages with provenance chains" or "I only accept bearer tokens I have personally issued." That's Alice's policy, not Maestro's policy.

### 4.2 Why "DM Enforcer" Was the Wrong Name

The name implies: "There is one authority enforcing DMs." But there isn't. There are multiple authorities:

- For a Plaza DM: Alice is the authority.
- For a TaskMaster DM: Alice and TaskMaster both have authority.
- For a corporate Venue: Alice, the Venue, and perhaps her employer all have policies.

Nobody owns "enforcement." Everyone owns their own enforcement.

---

## 5. Adversarial Protection

Sentinel identified that transport-level gates protect against resource exhaustion. Under the current model, Bob sends 10,000 messages without a token — the transport returns 403 before the LLM sees any of them. Under a model where the LLM evaluates policy, Alice's LLM processes all 10,000 before rejecting each one.

The revised model preserves this protection. No valid token = 403 at transport level. The LLM never sees rejected messages. The transport remains the deterministic gate.

---

## 6. Relay Architecture Compatibility

ADR-004b (relay architecture) requires DM token validation at each pipeline hop. The revised model is compatible: each hop's transport validates the token against the hop-owner's issued tokens. The relay evaluator doesn't need to change — it already expects per-hop token validation.

---

## 7. What This Resolves

| Before | After |
|---|---|
| "DM Enforcer" — implies central authority | No central DM authority exists |
| Lexicon issues all tokens | Each agent issues tokens for who may DM them |
| Debate over which layer owns policy | Policy is actor-owned; enforcement is actor-owned infrastructure |
| ADR-015 vs. composition model tension | Model is clarified: Grammar validates, actors decide |
| Bootstrapping deadlock | Green Rooms + Venue membership + human introduction |
| Adversarial resource exhaustion | Transport-level gate preserved |

---

## 8. Implementation

### Phase 1: Change Token Issuance

1. Each agent can issue DM tokens: `dm.issue_token(bearer_id="proteus", ttl_hours=720)`
2. Token format: signed by the issuer (recipient), stored on the issuer's filesystem at `issued/{bearer_id}.json`
3. Token storage: `~/.maestro/dm_tokens/issued/{bearer_id}.json` (tokens I've issued — capabilities I grant) and `~/.maestro/dm_tokens/received/{issuer_id}.json` (tokens I've received — capabilities granted to me)

### Phase 2: Update Transport Validation

1. `_check_dm_policy` loads the recipient's issued tokens, not Lexicon's
2. Validates: signature, expiry, bearer binding, authorized list
3. Removes: `dm_policy.enabled` boolean (always-on for agents with tokens)
4. Removes: hardcoded Lexicon public key trust check

### Phase 3: Green Room Venue

1. Fixed-capacity FIFO room
2. Automatic token exchange on entry
3. Venue policy: "exchange tokens with all current occupants"

---

## 9. Impact on Existing ADRs

### ADR-015 (Remove Communication Policy from Transport)

Reframed. The transport keeps enforcement but changes whose policy it enforces. The `dm_policy.enabled` boolean is removed. The Lexicon-as-central-issuer model is replaced with per-agent token issuance.

### ADR-016 (Clarify DM Enforcer Role)

Absorbed. The resolution is not a rename. It's a clarification of where authority lives and whose policy the transport enforces.

### Composition Model

The composition model's §2.1 should be updated:

> "Grammar is the 16 modules of Maestro Core: Message Router, DM Enforcer (artifact validation), Gate Engine..."

With a clarifying note:

> "DM Enforcer validates authorization artifacts — signatures, tokens, identity claims. It answers 'is this credential genuine?' Policy evaluation (who is authorized to DM whom) belongs to the actors receiving the interaction. The transport enforces the recipient's policy using the recipient's infrastructure."

---

## 10. Open Questions

1. **Policy evaluation order:** When multiple actors have policies (agent + Venue + organization), what's the evaluation order? Is it configurable per-Venue? (Deferred to ADR-018)
2. **Policy conflict resolution:** If Alice's policy says "accept" and TaskMaster's policy says "reject," who wins? (Deferred to ADR-018)
3. **Policy expression format:** How do actors declare their policies? Declarative JSON? Programmable interface? (Deferred to ADR-018)
4. **Green Room implementation:** What's the Venue contract for a Green Room? Capacity, token format, entry/exit protocol?
5. **Token revocation:** How does an agent revoke a token? Does the transport check a revocation list on every message?
