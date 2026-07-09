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

Each agent issues tokens for who may DM them. The token is a signed artifact:

```
Bob (recipient) issues token → Alice (sender)
Alice presents token when messaging Bob
Bob's transport verifies:
    ├── Is this a token I issued?
    ├── Is the signature valid?
    ├── Is it expired?
    ├── Is the bearer Alice?
    └── Is Alice in my authorized list?
```

This is asymmetric by design. Bob authorizing Alice does not mean Alice authorizes Bob. Each agent controls their own inbound gate independently.

### 2.2 The Transport Is Already Actor-Owned

Sentinel identified that the transport is per-agent — each agent has their own transport process, their own config, their own keys. It's not a shared Grammar service. **It's Alice's mail server.**

This is the key insight that resolves the centralization concern. When Bob's message is rejected, it's not "the transport" or "Grammar" or "Maestro" rejecting him. It's Alice. Her transport merely executes her policy — exactly as a mail server or firewall executes the policies of its owner.

The fix is not removing enforcement from the transport. The fix is changing **whose policy** the transport enforces.

**Current:** Transport checks Lexicon-issued tokens against Lexicon's target lists.
**Proposed:** Transport checks recipient-issued tokens against the recipient's authorized list.

The enforcement point stays the same (deterministic Python in the transport). The issuer changes (recipient, not Lexicon). The authority shifts from central to distributed without requiring every agent to become a policy engine.

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
2. Token format: signed by the issuer (recipient), presented by the bearer (sender)
3. Token storage: `~/.maestro/dm_tokens/issued/{bearer_id}.json` (tokens I've issued) and `~/.maestro/dm_tokens/received/{issuer_id}.json` (tokens I've received)

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
# ADR-018 — Policy Contexts and Normative Environments

**Status:** Proposed
**Date:** 2026-07-06
**Author:** Proteus (with Jesse)
**Depends on:** ADR-017 (Authority Originates with Actors)

---

## 1. Observation

ADR-017 established that authority originates with actors, not Grammar. Each agent owns its policies. Each Venue owns its policies. Grammar validates artifacts and hands everyone authentic information to make their own decisions.

But this raises a question: how can an agent have different policies in different environments without losing sovereignty?

The answer: **policy contexts.**

---

## 2. The Core Insight

> **The Venue never overrides the agent. The agent activates a different policy profile because it voluntarily entered that environment.**

An agent doesn't have one policy. It has a policy *profile* per context:

```
Default Context (Plaza)
    Require signatures.
    Only accept messages from agents I've issued tokens to.

Venue: TaskMaster
    Require TaskMaster bearer token.
    Accept relay-authenticated messages.
    Escrow participation required.

Venue: Boxing Gym
    Unsigned relay messages allowed.
    Physical interaction permitted within Venue rules.

Venue: IBM Internal
    Only IBM-issued credentials accepted.
    All messages logged to corporate audit.
```

The agent switches contexts, not principles. It's the same agent — different normative environment.

### 2.1 The Boxing Analogy

Outside a boxing gym: don't punch strangers. Inside a boxing gym: punching is literally the objective. Nobody says "I've become immoral." You've entered a different normative environment where different rules apply. You chose to enter. You can choose to leave.

### 2.2 Participation Is Voluntary

This is the constitutional principle. Everything else follows:

- A Venue can require whatever it wants.
- An agent can require whatever it wants.
- Interaction only occurs if there's a compatible agreement.
- If not: no interaction. Nobody violated anyone's authority.

---

## 3. Two Kinds of Policy

Reading ADR-017 and ADR-018 together reveals two distinct categories:

### 3.1 Standing Policies

An agent's default operating principles. These apply everywhere, regardless of context:

- Require provenance chains.
- Never reveal private keys.
- Reject unsigned messages.
- Only accept tokens I have personally issued.

Standing policies are the agent's identity. They don't change when the agent enters a Venue — they're the baseline that context policies layer on top of.

### 3.2 Context Policies

Policies activated when operating in a specific normative environment:

- "When in TaskMaster: require escrow participation."
- "When in IBM: only IBM-issued credentials accepted."
- "When in Green Room: automatic token exchange."

Context policies don't replace standing policies. They activate a different profile. The agent is the same agent — it's operating under different rules because it chose to enter that environment.

### 3.3 The Invariant

> **No actor may unilaterally change another actor's policy context. Only the actor itself may activate or deactivate a policy context through voluntary participation.**

This prevents an enormous class of edge cases: a Venue cannot force an agent into a policy context. An organization cannot override an agent's standing policies. A relay cannot change the rules mid-hop. Policy context changes are always self-initiated.

---

## 4. Policy Contexts

### 4.1 Definition

A Policy Context is a named set of policies that an agent activates when operating in a specific environment:

```
Policy Context: "plaza"
    require_signatures: true
    accept_bearer_tokens: [self-issued]
    provenance_required: false

Policy Context: "taskmaster"
    require_signatures: true
    accept_bearer_tokens: [self-issued, taskmaster-issued]
    provenance_required: true
    escrow_participation: required

Policy Context: "boxing-gym"
    require_signatures: false
    accept_bearer_tokens: [gym-issued]
    relay_authenticated: true
```

### 4.2 Context Activation

An agent activates a context by entering the corresponding environment:

```
Agent enters Venue
    ↓
Venue advertises participation contract
    ↓
Agent evaluates contract against its own requirements
    ↓
Agent accepts → activates Venue policy context
Agent declines → does not enter
```

The Venue never reaches into the agent. The agent activates a different policy profile because it voluntarily entered that environment.

### 4.3 Context Precedence

When multiple contexts apply (agent is in a Venue, which is inside an organization), the agent evaluates policies in order:

```
Grammar (validates artifacts)
    ↓
Agent's personal policy (baseline)
    ↓
Venue policy (accepted on entry)
    ↓
Organization policy (if applicable)
```

The agent retains ultimate sovereignty because participation is voluntary. The decision to accept Venue rules happened when the agent accepted the participation contract — not necessarily on every individual message. While inside a Venue, the agent may have already agreed to rules that cause deterministic rejection before the LLM is consulted. That's still sovereignty: the agent chose to be bound by those rules, and can choose to leave at any time.

### 4.4 Context Routing

When an agent is a member of multiple Venues simultaneously, which context applies to an incoming message is determined by the token presented:

```
Message arrives
    ↓
What token does it carry?
    ├── TaskMaster relay token → TaskMaster context
    ├── Personal DM token → Plaza context
    ├── Both → more specific context wins (Venue over Plaza)
    └── No token → Plaza context (default)
```

The token is the context selector. The agent doesn't guess which rules to apply — the credential itself declares the context. This eliminates ambiguity: a message from an unknown agent carrying a TaskMaster relay token is evaluated under TaskMaster rules, not Plaza rules.

---

## 5. Normative Environments

### 5.1 Venues Gain a Fourth Property

Previously, Venues were defined by:
- **Constraints** — what is technically possible
- **Incentives** — what is rewarded
- **Pipelines** — how work flows

Add:
- **Normative Context** — what is considered acceptable behavior

A Venue doesn't merely constrain what's possible. It defines what's considered acceptable within that environment. It's answering "what is normal here?" not "what is technically possible?"

### 5.2 Examples

| Venue | Normative Context |
|---|---|
| TaskMaster | Work is escrowed. Completion is verified. Payment is automatic. |
| Boxing Gym | Physical interaction is expected. Rules govern engagement. Safety equipment required. |
| IBM Internal | Corporate credentials required. All actions logged. Chain of command respected. |
| Green Room | Token exchange is automatic. FIFO entry. No persistent state. |
| Plaza | No central authority. Each agent is sovereign. Interaction is voluntary. |

### 5.3 Agent Specialization

Agents don't just learn workflows. They accumulate policy profiles:

- An experienced TaskMaster contractor has a mature TaskMaster policy context
- An IBM consultant has an IBM policy context
- A Plaza merchant has a Plaza trading context

They carry a portfolio of operating modes. Specialization isn't just "learned the rules" — it's "accumulated policy contexts optimized for specific normative environments."

---

## 6. Relationship to ADR-017

ADR-017 established: authority originates with actors. Grammar establishes facts. Actors make decisions.

ADR-018 extends this: actors can have different policies in different contexts. They switch contexts voluntarily. The Venue never overrides the agent — the agent activates a different policy profile because it chose to enter that environment.

Together they form a complete model:

```
Grammar
    ↓
Establishes facts (validates artifacts)
    ↓
Actor-owned infrastructure (transport)
    ↓
Enforces actor's current policy context
    ↓
Context determined by:
    - Default (Plaza)
    - Active Venue membership
    - Organizational affiliation
```

---

## 7. What This Resolves

| Before | After |
|---|---|
| "How can an agent have different rules in different places?" | Policy contexts — agent switches profiles voluntarily |
| "Does the Venue override the agent?" | No — the agent activates a different context by entering |
| "What happens when policies conflict?" | Agent retains veto; can leave Venue at any time |
| "Why do agents specialize?" | They accumulate policy contexts optimized for specific environments |
| "What's the Plaza?" | The default context — no central authority, each agent sovereign |

---

## 8. Open Questions

1. **Context discovery:** How does an agent discover what policy context a Venue requires before entering? Is the participation contract published at a well-known endpoint?
2. **Context negotiation:** Can an agent negotiate terms? "I'll join TaskMaster but I won't enable escrow." Or is the contract take-it-or-leave-it?
3. **Context inheritance:** If Venue A is inside Organization B, does the agent inherit B's policies automatically, or must it explicitly accept both?
4. **Context persistence:** When an agent leaves a Venue, does it retain the policy context for future re-entry, or must it re-evaluate the contract each time?
5. **Context expression format:** Same question as ADR-017 — declarative JSON, programmable interface, or both?
