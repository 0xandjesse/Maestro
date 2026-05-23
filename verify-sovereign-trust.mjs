// ============================================================
// Sovereign Trust Verification Script
// Runs the spec's three verification criteria.
// ============================================================

import { Maestro } from './dist/sdk/Maestro.js';
import { TrustPolicy } from './dist/trust/TrustPolicy.js';
import { verificationGate } from './dist/trust/VenueBouncer.js';
import { LocalKeyResolver } from './dist/resolvers/LocalKeyResolver.js';
import { generateKeyPair } from './dist/crypto/index.js';
import { createProvenance } from './dist/provenance/builder.js';

let passed = 0;
let failed = 0;

function assert(condition, label) {
  if (condition) {
    passed++;
    console.log(`  PASS: ${label}`);
  } else {
    failed++;
    console.error(`  FAIL: ${label}`);
  }
}

console.log('\n=== Sovereign Trust Verification ===\n');

// ---- Criterion 1: Unsigned P2P message delivers ----
console.log('Criterion 1: Unsigned P2P message delivers (neutral pipe)');
{
  const unsignedMessage = {
    id: 'msg-unsigned-1',
    type: 'direct',
    content: 'Hello, no provenance here',
    sender: { agentId: 'Alpha', wallet: '0xAlpha' },
    recipient: 'Beta',
    timestamp: Date.now(),
    version: '3.2',
  };

  assert(unsignedMessage.extensions === undefined, 'message has no extensions (no provenance)');
  assert(unsignedMessage.sender.agentId === 'Alpha', 'sender.agentId is Alpha');
  assert(unsignedMessage.recipient === 'Beta', 'recipient is Beta');

  const maestro = new Maestro({ agentId: 'Beta' });
  let received = false;
  maestro.onMessage('direct', () => { received = true; });
  const result = await maestro.receive(unsignedMessage);
  assert(result.accepted === true, 'router.dispatch() accepted unsigned message');
  assert(received === true, 'handler fired for unsigned message');
}

// ---- Criterion 2: Strict agent drops unsigned messages ----
console.log('\nCriterion 2: Strict agent drops unsigned messages (sovereign firewall)');
{
  const unsignedMessage = {
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
  assert(result.accept === false, 'strict policy rejects unsigned');
  assert(result.reason === 'missing_provenance', `reason is 'missing_provenance' (got: ${result.reason})`);

  const { privateKey, publicKey } = generateKeyPair();
  const resolver = new LocalKeyResolver();
  resolver.register('Alpha', publicKey);

  const signedMessage = {
    id: 'msg-signed-1',
    type: 'direct',
    content: 'Hello with provenance',
    sender: { agentId: 'Alpha', wallet: '0xAlpha' },
    recipient: 'Beta',
    timestamp: Date.now(),
    version: '3.2',
  };
  const provenance = await createProvenance(signedMessage, privateKey, 'full');
  signedMessage.extensions = { provenance };

  const strictPolicy = new TrustPolicy({ level: 'strict', resolver });
  const ok = await strictPolicy.evaluate(signedMessage);
  assert(ok.accept === true, 'strict policy accepts valid provenance');
  assert(ok.label === 'verified', `label is 'verified' (got: ${ok.label})`);

  const permissive = new TrustPolicy({ level: 'permissive' });
  const permResult = await permissive.evaluate(unsignedMessage);
  assert(permResult.accept === true, 'permissive policy accepts unsigned');
  assert(permResult.label === '[unverified]', `permissive labels [unverified] (got: ${permResult.label})`);

  const selective = new TrustPolicy({ level: 'selective', whitelist: ['0xFriend'] });
  const selResult = await selective.evaluate(unsignedMessage);
  assert(selResult.accept === false, 'selective policy drops non-whitelisted');
  assert(selResult.reason?.includes('sender_not_whitelisted'), 'selective reason mentions whitelist');
}

// ---- Criterion 3: Venue with required provenance rejects missing provenance ----
console.log('\nCriterion 3: Venue Bouncer rejects unsigned capability (venue gate)');
{
  const unsignedCapability = {
    id: 'msg-unsigned-3',
    type: 'capability',
    content: 'Install CryptoLib v2.1',
    sender: { agentId: 'Attacker' },
    recipient: '*',
    timestamp: Date.now(),
    version: '3.2',
  };

  const venuePolicy = {
    requiredFor: ['capability', 'financial'],
    minChainLength: 1,
    allowTruncated: false,
  };

  const gateResult = verificationGate(unsignedCapability, venuePolicy);
  assert(gateResult.allowed === false, 'venue gate blocks unsigned capability');
  assert(gateResult.error === 'ProvenanceRequired', `error is ProvenanceRequired (got: ${gateResult.error})`);
  assert(gateResult.reason?.includes('provenance_required_for_capability'), 'reason mentions capability');

  const { privateKey, publicKey } = generateKeyPair();
  const signedCapability = {
    id: 'msg-signed-2',
    type: 'capability',
    content: 'Install CryptoLib v2.1',
    sender: { agentId: 'Alpha', wallet: '0xAlpha' },
    recipient: '*',
    timestamp: Date.now(),
    version: '3.2',
  };
  const prov = await createProvenance(signedCapability, privateKey, 'full');
  signedCapability.extensions = { provenance: prov };

  const relaxedPolicy = {
    requiredFor: ['capability'],
    minChainLength: 0,
    allowTruncated: true,
  };
  const okGate = verificationGate(signedCapability, relaxedPolicy);
  assert(okGate.allowed === true, 'venue gate allows signed capability');
}

// ---- Criterion 3b: Maestro.receive() wires the Venue gate ----
console.log('\nCriterion 3b: Maestro.receive() blocks venue messages at the gate');
{
  const host = new Maestro({ agentId: 'Host' });
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

  const unsignedCapability = {
    id: 'msg-unsigned-3',
    type: 'capability',
    content: 'Install CryptoLib v2.1',
    sender: { agentId: 'Attacker' },
    recipient: 'Host',
    venueId: handle.connectionId,
    timestamp: Date.now(),
    version: '3.2',
  };

  const blockResult = await host.receive(unsignedCapability);
  assert(blockResult.accepted === false, 'Maestro.receive() drops unsigned capability in venue');
  assert(blockResult.reason?.includes('provenance_required'), `reason contains provenance_required (got: ${blockResult.reason})`);

  const unsignedChat = {
    id: 'msg-unsigned-6',
    type: 'chat',
    content: 'Hello everyone',
    sender: { agentId: 'Guest' },
    recipient: 'Host',
    venueId: handle.connectionId,
    timestamp: Date.now(),
    version: '3.2',
  };
  const passResult = await host.receive(unsignedChat);
  assert(passResult.accepted === true, 'Maestro.receive() allows chat in same venue');
}

console.log(`\n=== Results: ${passed} passed, ${failed} failed ===\n`);
if (failed > 0) process.exit(1);
