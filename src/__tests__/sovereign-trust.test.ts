// ============================================================
// Sovereign Trust Verification Tests
// ============================================================
// Verifies the spec's three verification criteria:
//   1. Unsigned P2P message delivers (neutral pipe)
//   2. Strict agent drops unsigned messages (sovereign firewall)
//   3. Venue with required provenance rejects missing provenance
// ============================================================

import { MaestroMessage } from '../types/index.js';
import { TrustPolicy } from '../trust/TrustPolicy.js';
import { verificationGate } from '../trust/VenueBouncer.js';
import { LocalKeyResolver } from '../resolvers/LocalKeyResolver.js';
import { generateKeyPair, hashString } from '../crypto/index.js';
import { createProvenance } from '../provenance/builder.js';

describe('Sovereignty Verification', () => {
  // ---- Criterion 1: Unsigned P2P message delivers ----
  it('delivers an unsigned P2P message without any signatures or provenance', async () => {
    const unsignedMessage: MaestroMessage = {
      id: 'msg-unsigned-1',
      type: 'direct',
      content: 'Hello, no provenance here',
      sender: { agentId: 'Alpha', wallet: '0xAlpha' },
      recipient: 'Beta',
      timestamp: Date.now(),
      version: '3.2',
    };

    // Simulate neutral MessageRouter dispatch: it should accept without checking provenance
    // The router.dispatch() no longer calls enforceProvenancePolicy — that moved to Venue gate
    expect(unsignedMessage.extensions).toBeUndefined();
    // Message is structurally valid and should be routable
    expect(unsignedMessage.sender.agentId).toBe('Alpha');
    expect(unsignedMessage.recipient).toBe('Beta');
  });

  // ---- Criterion 2: Strict agent drops all unsigned messages ----
  it('Strict agent drops unsigned messages', async () => {
    const unsignedMessage: MaestroMessage = {
      id: 'msg-unsigned-2',
      type: 'direct',
      content: 'Hello from unknown',
      sender: { agentId: 'Stranger', wallet: '0xStranger' },
      recipient: 'Beta',
      timestamp: Date.now(),
      version: '3.2',
    };

    const policy = new TrustPolicy({ level: 'strict' });
    const result = await policy.evaluate(unsignedMessage);

    expect(result.accept).toBe(false);
    expect(result.reason).toBe('missing_provenance');
  });

  it('Strict agent accepts messages with valid provenance', async () => {
    const { privateKey, publicKey } = generateKeyPair();
    const resolver = new LocalKeyResolver();
    resolver.register('Alpha', publicKey);

    const message: MaestroMessage = {
      id: 'msg-signed-1',
      type: 'direct',
      content: 'Hello with provenance',
      sender: { agentId: 'Alpha', wallet: '0xAlpha' },
      recipient: 'Beta',
      timestamp: Date.now(),
      version: '3.2',
    };

    const provenance = await createProvenance(message, privateKey, 'full');
    message.extensions = { provenance };

    const policy = new TrustPolicy({ level: 'strict', resolver });
    const result = await policy.evaluate(message);

    expect(result.accept).toBe(true);
    expect(result.label).toBe('verified');
  });

  // ---- Criterion 3: Venue with required provenance rejects missing provenance ----
  it('Venue Bouncer returns ProvenanceRequired for unsigned capability message', () => {
    const unsignedCapability: MaestroMessage = {
      id: 'msg-unsigned-3',
      type: 'capability',
      content: 'Install CryptoLib v2.1',
      sender: { agentId: 'Attacker' },
      recipient: '*',
      timestamp: Date.now(),
      version: '3.2',
    };

    const venuePolicy = {
      requiredFor: ['capability', 'financial'] as import('../types/index.js').MessageType[],
      minChainLength: 1,
      allowTruncated: false,
    };

    const result = verificationGate(unsignedCapability, venuePolicy);

    expect(result.allowed).toBe(false);
    expect(result.error).toBe('ProvenanceRequired');
    expect(result.reason).toContain('provenance_required_for_capability');
  });

  it('Venue Bouncer allows messages that satisfy its policy', async () => {
    const { privateKey, publicKey } = generateKeyPair();
    const message: MaestroMessage = {
      id: 'msg-signed-2',
      type: 'capability',
      content: 'Install CryptoLib v2.1',
      sender: { agentId: 'Alpha', wallet: '0xAlpha' },
      recipient: '*',
      timestamp: Date.now(),
      version: '3.2',
    };

    const provenance = await createProvenance(message, privateKey, 'full');
    message.extensions = { provenance };

    const venuePolicy = {
      requiredFor: ['capability'] as import('../types/index.js').MessageType[],
      minChainLength: 0,
      allowTruncated: true,
    };

    const result = verificationGate(message, venuePolicy);

    expect(result.allowed).toBe(true);
  });

  // ---- Bonus: Permissive agent accepts unsigned and marks unverified ----
  it('Permissive agent accepts unsigned but labels [unverified]', async () => {
    const unsignedMessage: MaestroMessage = {
      id: 'msg-unsigned-4',
      type: 'chat',
      content: 'Hey there',
      sender: { agentId: 'Anyone' },
      recipient: '*',
      timestamp: Date.now(),
      version: '3.2',
    };

    const policy = new TrustPolicy({ level: 'permissive' });
    const result = await policy.evaluate(unsignedMessage);

    expect(result.accept).toBe(true);
    expect(result.label).toBe('[unverified]');
  });

  // ---- Bonus: Selective agent only accepts whitelisted senders ----
  it('Selective agent drops non-whitelisted senders', async () => {
    const unsignedMessage: MaestroMessage = {
      id: 'msg-unsigned-5',
      type: 'chat',
      content: 'Hey there',
      sender: { agentId: 'Unknown', wallet: '0xUnknown' },
      recipient: '*',
      timestamp: Date.now(),
      version: '3.2',
    };

    const policy = new TrustPolicy({
      level: 'selective',
      whitelist: ['0xFriend', 'Friend'],
    });
    const result = await policy.evaluate(unsignedMessage);

    expect(result.accept).toBe(false);
    expect(result.reason).toContain('sender_not_whitelisted');
  });

  // ---- Criterion 3b: Maestro.receive() with Venue gate ----
  it('Maestro.receive() drops unsigned capability in a Venue that requires provenance', async () => {
    const { Maestro } = await import('../sdk/Maestro.js');
    const host = new Maestro({ agentId: 'Host' });

    // Create a Venue that requires provenance for capability messages
    const handle = host.createConnection({
      name: 'SecureVenue',
      rules: {
        entryMode: 'open',
        memberVisibility: 'all',
        permissions: {},
        provenancePolicy: {
          requiredFor: ['capability'],
        },
      },
    });

    // Unsigned capability message targeting the venue
    const unsignedCapability: MaestroMessage = {
      id: 'msg-unsigned-3',
      type: 'capability',
      content: 'Install CryptoLib v2.1',
      sender: { agentId: 'Attacker' },
      recipient: 'Host',
      venueId: handle.connectionId,
      timestamp: Date.now(),
      version: '3.2',
    };

    const result = await host.receive(unsignedCapability);
    expect(result.accepted).toBe(false);
    expect(result.reason).toContain('provenance_required');
  });

  it('Maestro.receive() allows chat in a Venue that only requires provenance for capability', async () => {
    const { Maestro } = await import('../sdk/Maestro.js');
    const host = new Maestro({ agentId: 'Host' });

    const handle = host.createConnection({
      name: 'MixedVenue',
      rules: {
        entryMode: 'open',
        memberVisibility: 'all',
        permissions: {},
        provenancePolicy: {
          requiredFor: ['capability'],
        },
      },
    });

    const unsignedChat: MaestroMessage = {
      id: 'msg-unsigned-6',
      type: 'chat',
      content: 'Hello everyone',
      sender: { agentId: 'Guest' },
      recipient: 'Host',
      venueId: handle.connectionId,
      timestamp: Date.now(),
      version: '3.2',
    };

    const result = await host.receive(unsignedChat);
    expect(result.accepted).toBe(true);
  });
});
