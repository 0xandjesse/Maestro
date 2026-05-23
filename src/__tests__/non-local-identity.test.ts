// ============================================================
// Maestro Protocol — Non-Local Identity & Contact Card Exchange
// ============================================================
//
// Simulates two agents on different virtual endpoints exchanging
// Contact Cards and sending a message. Verifies the wallet-based
// global identity model (no nUID, no venue scoping).
//
// Spec: CL-songbird-90ff994b
// ============================================================

import { Maestro } from '../sdk/Maestro.js';

const ALICE_WALLET = '0xALICE1234567890abcdef1234567890abcdef12';
const BOB_WALLET   = '0xBOB9876543210fedcba9876543210fedcba9876';

function makeMaestro(agentId: string, wallet: string, port: number): Maestro {
  return new Maestro({
    agentId,
    wallet,
    capabilities: ['messaging', 'blackboard'],
    transport: { port },
    publicKey: 'deadbeef' + agentId,
  });
}

// ----------------------------------------------------------
// Helpers
// ----------------------------------------------------------

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

// ----------------------------------------------------------
// Test: Contact Card Exchange via Join Handshake
// ----------------------------------------------------------

describe('Non-Local Identity (wallet-based UID)', () => {
  let alice: Maestro;
  let bob: Maestro;

  afterEach(async () => {
    await alice?.stop();
    await bob?.stop();
  });

  test('ContactCard uses walletAddress and friendlyName', async () => {
    alice = makeMaestro('alice', ALICE_WALLET, 47701);
    await alice.start();

    const handle = alice.openConnection('test-conn');
    expect(handle).toBeDefined();

    // Alice's host contact card must reflect wallet-based identity
    const hostCard = alice.connectionManager.getHostContactCard();
    if (!hostCard) throw new Error('hostContactCard not set');
    expect(hostCard!.walletAddress).toBe(ALICE_WALLET);
    expect(hostCard!.friendlyName).toBe('alice');
    expect(hostCard!.endpoint).toMatch(/47701/);
    expect(hostCard!.capabilities).toContain('messaging');
    expect(hostCard!.issuedAt).toBeGreaterThan(0);
    // No nuid / displayName remnants
    expect(hostCard!).not.toHaveProperty('nuid');
    expect(hostCard!).not.toHaveProperty('displayName');
  });

  test('Join handshake exchanges walletAddress + friendlyName', async () => {
    alice = makeMaestro('alice', ALICE_WALLET, 47702);
    bob   = makeMaestro('bob',   BOB_WALLET,   47703);
    await alice.start();
    await bob.start();

    const aliceConn = alice.openConnection('peer-conn');
    const connectionId = aliceConn.connectionId;

    // Bob joins via local join (same process, different managers)
    const response = bob.join(connectionId, alice.connectionManager);

    expect(response.status).toBe('accepted');
    expect(response.hostContactCard).toBeDefined();
    expect(response.hostContactCard!.walletAddress).toBe(ALICE_WALLET);
    expect(response.hostContactCard!.friendlyName).toBe('alice');
    expect(response.hostContactCard!.endpoint).toMatch(/47702/);
  });

  test('Message sender carries wallet identity', async () => {
    alice = makeMaestro('alice', ALICE_WALLET, 47704);
    bob   = makeMaestro('bob',   BOB_WALLET,   47705);
    await alice.start();
    await bob.start();

    const aliceConn = alice.openConnection('msg-conn');
    const connectionId = aliceConn.connectionId;

    bob.join(connectionId, alice.connectionManager);

    // Bob sends a direct message to Alice inside the Connection
    const bobHandle = bob.getConnection(connectionId)!;
    const msg = await bobHandle.send('alice', 'hello from bob');

    expect(msg.sender.agentId).toBe('bob');
    expect(msg.sender.wallet).toBe(BOB_WALLET);
    expect(msg.sender).not.toHaveProperty('nuid');
  });
});
