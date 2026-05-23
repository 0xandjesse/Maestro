import { generateKeyPair } from '../crypto/index.js';
import { createMessage } from '../message/index.js';
import {
  addAttestation,
  createProvenance,
  truncateProvenance,
} from '../provenance/builder.js';
import {
  verifyProvenance,
  verifyTruncatedChainSegments,
} from '../provenance/verifier.js';
import { LocalKeyResolver } from '../resolvers/LocalKeyResolver.js';
import { getProvenanceExtension } from '../extensions/index.js';
import { MaestroMessage } from '../types/index.js';

// ----------------------------------------------------------
// Test fixtures
// ----------------------------------------------------------

async function makeAgent(id: string) {
  const { privateKey, publicKey } = generateKeyPair();
  return { id, privateKey, publicKey };
}

async function buildChain(agentCount: number) {
  const agents = await Promise.all(
    Array.from({ length: agentCount }, (_, i) => makeAgent(`Agent${i}`)),
  );

  const resolver = new LocalKeyResolver();
  for (const a of agents) resolver.register(a.id, a.publicKey);

  // Agent0 creates the message
  const origin = agents[0];
  let message = await createMessage(
    'Use CryptoLib v2.1 for encryption',
    { agentId: origin.id },
    origin.privateKey,
    { type: 'capability', provenanceMode: 'full' },
  );

  // Each subsequent agent attests receipt and forwards
  for (let i = 1; i < agents.length; i++) {
    const agent = agents[i];
    const prevAgent = agents[i - 1];
    const prov = getProvenanceExtension(message);
    const newProv = await addAttestation(
      prov!,
      prevAgent.id,
      agent.id,
      agent.privateKey,
    );
    message = {
      ...message,
      extensions: { ...(message.extensions ?? {}), provenance: newProv },
    };
  }

  return { message, agents, resolver };
}

// ----------------------------------------------------------
// Full chain tests
// ----------------------------------------------------------

describe('Full provenance chain', () => {
  it('verifies a 1-hop chain (origin only)', async () => {
    const alpha = await makeAgent('Alpha');
    const resolver = new LocalKeyResolver();
    resolver.register('Alpha', alpha.publicKey);

    const message = await createMessage(
      'Hello world',
      { agentId: 'Alpha' },
      alpha.privateKey,
      { type: 'chat', provenanceMode: 'full' },
    );

    const result = await verifyProvenance(message, resolver);
    expect(result.valid).toBe(true);
    expect(result.status).toBe('valid');
  });

  it('verifies a 3-hop chain (Alpha → Beta → Gamma)', async () => {
    const { message, resolver } = await buildChain(3);
    const result = await verifyProvenance(message, resolver);
    expect(result.valid).toBe(true);
  });

  it('verifies a 5-hop chain', async () => {
    const { message, resolver } = await buildChain(5);
    const result = await verifyProvenance(message, resolver);
    expect(result.valid).toBe(true);
  });

  it('fails if content is tampered', async () => {
    const { message, resolver } = await buildChain(3);
    const tampered: MaestroMessage = { ...message, content: 'Use malware instead' };
    const result = await verifyProvenance(tampered, resolver);
    expect(result.valid).toBe(false);
    expect(result.status).toBe('invalid-content-hash');
  });

  it('fails if original signature is tampered', async () => {
    const { message, resolver } = await buildChain(3);
    const prov = getProvenanceExtension(message);
    const tampered: MaestroMessage = {
      ...message,
      extensions: { ...(message.extensions ?? {}), provenance: {
        ...prov!,
        originalSignature: 'deadbeef'.repeat(16),
      }},
    };
    const result = await verifyProvenance(tampered, resolver);
    expect(result.valid).toBe(false);
    expect(result.status).toBe('invalid-original-signature');
  });

  it('fails if an attestation link signature is tampered', async () => {
    const { message, resolver } = await buildChain(3);
    const prov = getProvenanceExtension(message);
    const chain = [...prov!.chain!];
    chain[0] = { ...chain[0], signature: 'deadbeef'.repeat(16) };
    const tampered: MaestroMessage = {
      ...message,
      extensions: { ...(message.extensions ?? {}), provenance: { ...prov!, chain } },
    };
    const result = await verifyProvenance(tampered, resolver);
    expect(result.valid).toBe(false);
    expect(result.status).toBe('invalid-chain-link');
    expect(result.failedLinkIndex).toBe(0);
  });

  it('fails if sender public key is unknown', async () => {
    const { message } = await buildChain(3);
    const emptyResolver = new LocalKeyResolver(); // no keys registered
    const result = await verifyProvenance(message, emptyResolver);
    expect(result.valid).toBe(false);
    expect(result.status).toBe('resolver-error');
  });

  it('returns missing-provenance when provenance is absent', async () => {
    const alpha = await makeAgent('Alpha');
    const resolver = new LocalKeyResolver();
    resolver.register('Alpha', alpha.publicKey);

    const message = await createMessage('Hello', { agentId: 'Alpha' });
    const result = await verifyProvenance(message, resolver);
    expect(result.valid).toBe(false);
    expect(result.status).toBe('missing-provenance');
  });
});

// ----------------------------------------------------------
// Truncation tests
// ----------------------------------------------------------

describe('Provenance truncation', () => {
  it('truncates a 5-hop chain to tail-only (2 recent hops)', async () => {
    const { message } = await buildChain(5);
    const prov = getProvenanceExtension(message);
    const truncated = truncateProvenance(prov!, 'tail-only', 2);
    expect(truncated.mode).toBe('tail-only');
    expect(truncated.truncatedChain!.recentHops).toHaveLength(2);
    expect(truncated.truncatedChain!.originNeighborhood).toHaveLength(0);
    expect(truncated.truncatedChain!.hiddenMiddleCount).toBe(2);
  });

  it('truncates a 5-hop chain to bookends', async () => {
    const { message } = await buildChain(5);
    const prov = getProvenanceExtension(message);
    const truncated = truncateProvenance(prov!, 'bookends', 2);
    expect(truncated.mode).toBe('bookends');
    expect(truncated.truncatedChain!.originNeighborhood).toHaveLength(1); // first hop
    expect(truncated.truncatedChain!.recentHops.length).toBeGreaterThanOrEqual(1);
    expect(truncated.truncatedChain!.hiddenMiddleCount).toBeGreaterThanOrEqual(0);
  });

  it('truncates a 8-hop chain to origin-neighborhood (3 origin + 2 recent)', async () => {
    const { message } = await buildChain(8);
    const prov = getProvenanceExtension(message);
    const truncated = truncateProvenance(prov!, 'origin-neighborhood', 2, 3);
    expect(truncated.mode).toBe('origin-neighborhood');
    expect(truncated.truncatedChain!.originNeighborhood).toHaveLength(3);
    expect(truncated.truncatedChain!.recentHops).toHaveLength(2);
    expect(truncated.truncatedChain!.hiddenMiddleCount).toBe(2); // hops 3,4 hidden (0-indexed: 3,4)
  });

  it('verifyTruncatedChainSegments validates origin neighborhood', async () => {
    const { message, resolver } = await buildChain(8);
    const prov = getProvenanceExtension(message);
    const truncated = truncateProvenance(prov!, 'origin-neighborhood', 2, 3);
    const truncatedMessage = {
      ...message,
      extensions: { ...(message.extensions ?? {}), provenance: truncated },
    };

    const ext = getProvenanceExtension(truncatedMessage);
    const result = await verifyTruncatedChainSegments(
      ext!,
      ext!.originalSignature,
      resolver,
    );
    expect(result.originSegmentValid).toBe(true);
    expect(result.recentSegmentInternallyValid).toBe(true);
    expect(result.hiddenMiddleCount).toBeGreaterThan(0);
  });

  it('throws if truncateProvenance called on non-full chain', async () => {
    const { message } = await buildChain(5);
    const prov = getProvenanceExtension(message);
    const truncated = truncateProvenance(prov!, 'bookends');
    expect(() => truncateProvenance(truncated, 'tail-only')).toThrow();
  });
});

// ----------------------------------------------------------
// Venue policy tests
// ----------------------------------------------------------

describe('Venue provenance policy enforcement', () => {
  it('rejects message without provenance when required', () => {
    const message: MaestroMessage = {
      id: '1',
      type: 'capability',
      content: 'test',
      sender: { agentId: 'Alpha' },
      recipient: 'Beta',
      timestamp: 1000,
      version: '3.2',
    };

    // Simulate Venue enforcement
    const requiresProvenance = (msg: MaestroMessage): boolean => {
      return msg.type === 'capability' && !getProvenanceExtension(msg);
    };

    expect(requiresProvenance(message)).toBe(true);
  });
});
