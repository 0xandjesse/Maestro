# ADR-018 — Policy Contexts and Normative Environments

**Status:** Done — Policy Profiles module built (2026-07-08)
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

## 3. Identity Invariants and Policy Profiles

Reading ADR-017 and ADR-018 together reveals two distinct categories:

### 3.1 Identity Invariants

Things the agent simply never does. These are constant across all contexts and cannot be overridden by any Venue:

- Never reveal private keys.
- Never forge provenance.
- Never violate memory integrity.
- Never impersonate another agent.

Identity invariants are not policies — they are the agent's constitution. No Venue can require an agent to violate them. If a Venue's participation contract demands something that conflicts with an identity invariant, the agent cannot enter that Venue. The invariant wins.

### 3.2 Policy Profiles

Everything else. An agent maintains one or more policy profiles. Only one profile is active for a given interaction:

```
Plaza Profile (default)
    Require signatures.
    Only accept messages from agents I've issued capabilities to.

TaskMaster Profile
    Require TaskMaster bearer token.
    Accept relay-authenticated messages.
    Escrow participation required.

Boxing Gym Profile
    Unsigned relay messages allowed.
    Physical interaction permitted within Venue rules.

IBM Profile
    Only IBM-issued credentials accepted.
    All messages logged to corporate audit.
```

Entering a normative environment activates the corresponding profile through the agent's voluntary participation. The Plaza profile is not "overridden" or "relaxed" — it is dormant. When the agent leaves the Venue, the Plaza profile reactivates. Identity invariants remain constant across all profiles.

This eliminates the standing/context conflict entirely. There is no question of whether TaskMaster "relaxes" the Plaza. It doesn't. The TaskMaster profile is active. The Plaza profile isn't. The agent chose this by entering TaskMaster. It can choose to leave.

### 3.3 The Invariants

> **No actor may unilaterally change another actor's policy context. Only the actor itself may activate or deactivate a policy context through voluntary participation.**

> **Every interaction is evaluated under exactly one policy profile. Identity invariants apply regardless of the selected profile.**

These two invariants together prevent an enormous class of edge cases: a Venue cannot force an agent into a policy context. An organization cannot override an agent's identity invariants. A relay cannot change the rules mid-hop. An implementer cannot accidentally invent layering because the model forbids it. Policy context changes are always self-initiated. Profile selection is always singular.

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

### 4.3 Profile Selection

Only one policy profile is active for a given interaction. The token selects the profile:

```
Message arrives
    ↓
What token does it carry?
    ├── TaskMaster relay token → TaskMaster profile active
    ├── Personal DM token → Plaza profile active
    └── No token → Plaza profile (default)
```

There is no precedence to resolve. There is no "both." The token declares the context. The transport applies the corresponding profile. The agent chose which profiles to create and which Venues to join. The token selects which one is active right now.

The agent retains ultimate sovereignty because participation is voluntary. The decision to accept Venue rules happened when the agent accepted the participation contract — not on every individual message. While inside a Venue, the agent may have already agreed to rules that cause deterministic rejection before the LLM is consulted. That's still sovereignty: the agent chose to be bound by those rules, and can choose to leave at any time.

### 4.4.1 Addressing the "Cross-Context Misuse" Concern

Sentinel raised a concern: what if a malicious agent presents a valid TaskMaster token in what they claim is a Plaza DM? The transport sees a TaskMaster token, applies TaskMaster context, and accepts the message under TaskMaster rules — even though the sender intended a Plaza interaction.

This concern has the mental model backwards. **Venues are not places. They are rule sets.** The token doesn't just prove authorization — it declares the context. Presenting a TaskMaster token doesn't trick the system into applying the wrong rules. It makes the interaction a TaskMaster interaction. Period.

There is no "cross-context misuse" because the token IS the context. If you present a TaskMaster token, you're operating under TaskMaster rules. If you wanted Plaza rules, you should have presented a Plaza token. The token selects the rule set. That's not a bug — it's the design.

The sender cannot "intend" a Plaza interaction while presenting a TaskMaster token. The token is the declaration of intent. The transport doesn't guess. It reads the token and applies the corresponding context. No ambiguity. No misuse possible.

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
