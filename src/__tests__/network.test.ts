// ============================================================
// Maestro Protocol — Network Transport Integration Tests
// ============================================================
//
// Tests real HTTP delivery between two Maestro instances
// running on different ports in the same process.
//
// These tests bind to actual TCP ports, so they're kept
// separate from unit tests. Run with: npm test
// ============================================================

import { Maestro } from '../sdk/Maestro.js';
import { MaestroMessage } from '../types/index.js';
import { deliverMessage } from '../transport/NetworkDelivery.js';

// Use high ports to avoid conflicts
const PORT_A = 47801;
const PORT_B = 47802;

function webhookUrl(port: number): string {
  return `http://localhost:${port}/message`;
}

async function makeStarted(agentId: string, port: number): Promise<Maestro> {
  const m = new Maestro({ agentId, transport: { port } });
  await m.start();
  return m;
}

// ----------------------------------------------------------
// HttpTransport — basic HTTP
// ----------------------------------------------------------

describe('HttpTransport — basic HTTP', () => {
  let agent: Maestro;

  beforeEach(async () => {
    agent = await makeStarted('Alpha', PORT_A);
  });

  afterEach(async () => {
    await agent.stop();
  });

  it('returns 404 for non-message paths', async () => {
    const res = await fetch(`http://localhost:${PORT_A}/other`);
    expect(res.status).toBe(404);
  });

  it('returns 400 for malformed JSON', async () => {
    const res = await fetch(`http://localhost:${PORT_A}/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: 'not json',
    });
    expect(res.status).toBe(400);
  });

  it('returns 400 for missing required fields', async () => {
    const res = await fetch(`http://localhost:${PORT_A}/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: 'hello' }), // missing id, type, sender
    });
    expect(res.status).toBe(400);
  });

  it('accepts a valid message and returns 200', async () => {
    const msg: MaestroMessage = {
      id: 'test-1',
      type: 'direct',
      content: 'hello',
      sender: { agentId: 'Beta' },
      recipient: 'Alpha',
      timestamp: Date.now(),
      version: '3.2',
    };

    const res = await fetch(`http://localhost:${PORT_A}/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(msg),
    });

    expect(res.status).toBe(200);
    const body = await res.json() as { accepted: boolean };
    expect(body.accepted).toBe(true);
  });
});

// ----------------------------------------------------------
// NetworkTransport — end-to-end delivery
// ----------------------------------------------------------

describe('NetworkTransport — cross-agent delivery', () => {
  let alpha: Maestro;
  let beta: Maestro;

  beforeEach(async () => {
    alpha = await makeStarted('Alpha', PORT_A);
    beta = await makeStarted('Beta', PORT_B);
  });

  afterEach(async () => {
    await alpha.stop();
    await beta.stop();
  });

  it('delivers a message from Alpha to Beta via HTTP', async () => {
    const received: MaestroMessage[] = [];
    beta.onMessage('*', (msg) => { received.push(msg); });

    // Alpha creates a connection and builds a message to Beta
    const connection = alpha.openConnection('Room');
    const msg = await connection.send('Beta', 'Hello over HTTP');

    // Deliver directly to Beta's message endpoint
    const result = await deliverMessage(webhookUrl(PORT_B), msg);

    expect(result.ok).toBe(true);
    expect(result.statusCode).toBe(200);

    // Give Beta's async handler a moment to run
    await new Promise(r => setTimeout(r, 50));
    expect(received.length).toBeGreaterThan(0);
    expect(received[0].content).toBe('Hello over HTTP');
    expect(received[0].sender.agentId).toBe('Alpha');
  });

  it('delivers a broadcast message to multiple agents', async () => {
    const receivedByBeta: MaestroMessage[] = [];
    beta.onMessage('*', (msg) => { receivedByBeta.push(msg); });

    const connection = alpha.openConnection('Room');
    const msg = await connection.broadcast('Hello everyone');

    // Send to Beta
    const result = await deliverMessage(webhookUrl(PORT_B), msg);

    expect(result.ok).toBe(true);
    await new Promise(r => setTimeout(r, 50));
    expect(receivedByBeta.length).toBeGreaterThan(0);
    expect(receivedByBeta[0].type).toBe('broadcast');
  });

  it('returns failure for unreachable endpoint', async () => {
    const connection = alpha.openConnection('Room');
    const msg = await connection.send('Ghost', 'Hello');

    const result = await deliverMessage('http://localhost:19999/message', msg);
    expect(result.ok).toBe(false);
  });

  it('returns rejected for policy rejection via receive()', async () => {
    // Beta has a strict Connection that requires provenance on capability messages
    const secureConnection = beta.createConnection({
      name: 'Secure Connection',
      rules: {
        entryMode: 'open',
        memberVisibility: 'all',
        permissions: {
          lead: ['message:send', 'message:broadcast', 'blackboard:read', 'blackboard:write', 'member:invite', 'member:remove', 'role:assign', 'venue:close', 'venue:transfer'],
          worker: ['message:send', 'blackboard:read', 'blackboard:write'],
        },
        provenancePolicy: { requiredFor: ['capability'] },
      },
    });

    // Alpha sends a capability message without provenance to Beta
    const msg: MaestroMessage = {
      id: 'cap-1',
      type: 'capability',
      content: 'use my library',
      sender: { agentId: 'Alpha' },
      recipient: 'Beta',
      timestamp: Date.now(),
      version: '3.2',
      stageId: secureConnection.connectionId,
    };

    // Use receive() to test policy enforcement synchronously
    const result = await beta.receive(msg);
    expect(result.accepted).toBe(false);
    expect(result.reason).toContain('provenance_required');
  });
});

// ----------------------------------------------------------
// Maestro.start() / stop() lifecycle
// ----------------------------------------------------------

describe('Maestro lifecycle with HTTP', () => {
  it('is idempotent on start', async () => {
    const m = await makeStarted('Alpha', PORT_A);
    await expect(m.start()).resolves.not.toThrow();
    await m.stop();
  });

  it('cleans up on stop', async () => {
    const m = await makeStarted('Alpha', PORT_A);
    await m.stop();

    // Port should be free — another agent can bind to it
    const m2 = await makeStarted('Beta', PORT_A);
    await m2.stop();
  });

  it('exposes correct webhook endpoint via transport', async () => {
    const m = await makeStarted('Alpha', PORT_A);
    // HttpTransport registers at /message; verify it's reachable
    const res = await fetch(`http://localhost:${PORT_A}/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: 'ping',
        type: 'direct',
        sender: { agentId: 'Test' },
        recipient: 'Alpha',
        timestamp: Date.now(),
        version: '3.2',
      }),
    });
    expect(res.status).toBe(200);
    await m.stop();
  });
});
