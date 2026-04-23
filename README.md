# Maestro Protocol

**Open coordination layer for autonomous agents.**

Maestro is the TCP/IP of agent coordination — a minimal, neutral protocol that lets agents communicate, coordinate, and establish trust without central authority.

---

## What It Is

Maestro provides:

- **Message transport** — typed messages between agents, with Venue context
- **Optional provenance chains** — cryptographic attestation of message custody
- **Pluggable identity** — public key resolution via LOCR, DID, or custom registries
- **No governance at L0** — enforcement lives at Venues (L1) and services (L2)

## What It Is Not

- A reputation system
- A governance layer
- A surveillance infrastructure

The protocol provides primitives. Agents and Venues determine policy.

---

## Core Concepts

### MaestroMessage

Every message in the protocol:

```typescript
interface MaestroMessage {
  id: string;
  type: MessageType;        // chat | capability | software | financial | ...
  content: string;
  sender: AgentIdentity;
  recipient: string;        // agentId or '*' for broadcast
  timestamp: number;
  provenance?: Provenance;  // optional — see below
  venueId?: string;
  replyTo?: string;
}
```

### Provenance Chains

Optional cryptographic attestation. Recipients sign receipt, creating an unforgeable chain of custody.

**Four modes:**

| Mode | Use When |
|------|----------|
| `full` | Maximum accountability (financial, software) |
| `bookends` | Default — origin + recent custody |
| `origin-neighborhood` | Forensics — expose origin's propagation pattern |
| `tail-only` | Privacy — hide origin, show recent custody only |

### Incentive Model

Provenance is not enforced by the protocol. Agents attest because recipients demand it:

> "If you want me to act on this recommendation, prove the chain."

Venues enforce policy at L1. Market determines adoption.

---

## Quick Start

```typescript
import {
  generateKeyPair,
  createMessage,
  addAttestation,
  verifyProvenance,
  LocalKeyResolver,
} from '@maestro-protocol/core';

// Generate key pairs
const alpha = generateKeyPair();
const beta = generateKeyPair();

// Set up resolver
const resolver = new LocalKeyResolver();
resolver.register('Alpha', alpha.publicKey);
resolver.register('Beta', beta.publicKey);

// Alpha creates a message with provenance
const message = await createMessage(
  'Use CryptoLib v2.1 for encryption',
  { agentId: 'Alpha' },
  alpha.privateKey,
  { type: 'capability', provenanceMode: 'full' },
);

// Beta attests receipt and forwards
const forwarded = {
  ...message,
  provenance: await addAttestation(
    message.provenance!,
    'Alpha',
    'Beta',
    beta.privateKey,
  ),
};

// Verify the chain
const result = await verifyProvenance(forwarded, resolver);
console.log(result.valid); // true
```

---

## Truncation

For long chains, truncate to preserve privacy while retaining useful information:

```typescript
import { truncateProvenance } from '@maestro-protocol/core';

// Bookend truncation: keep origin + recent hops, hide middle
const truncated = truncateProvenance(message.provenance!, 'bookends', 2);

// Origin neighborhood: expose origin's first 3 hops for L2 analysis
const forensic = truncateProvenance(message.provenance!, 'origin-neighborhood', 2, 3);
```

`hiddenMiddleCount` is always present — a large count warrants additional scrutiny.

---

## Key Resolver

Implement `PublicKeyResolver` for your deployment:

```typescript
interface PublicKeyResolver {
  resolve(agentId: string): Promise<Uint8Array | null>;
}
```

Built-in: `LocalKeyResolver` (in-memory, for dev/testing).

Production options: LOCR registry, DID document, on-chain contract.

---

## Philosophy

> L0 (Maestro) provides the primitive.  
> L1 (Venues) provides enforcement.  
> L2 (services) provides analysis.  
> L3 (agents) provides judgment.

The immune system emerges. It is not designed in.

---

## Status

`v0.1.0` — Core provenance primitive. Protocol spec: [Maestro-Spec-v3.2](https://github.com/0xandjesse/Maestro).

## License

MIT
