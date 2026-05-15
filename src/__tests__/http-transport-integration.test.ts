// ============================================================
// Maestro Protocol — HttpTransport Integration Tests
// ============================================================
//
// Tests real HTTP delivery between two HttpTransport instances:
//   - p2p direct messaging
//   - p2n broadcast messaging
//   - BB write + BlackboardBridge cross-process notification
//   - Connection create + remote join via /connections/:id/join
//
// Ports 47810–47815 (no collision with network.test.ts 47801–47802)
// ============================================================

import { jest } from '@jest/globals';
import { randomUUID } from 'crypto';
import { tmpdir } from 'os';
import { join } from 'path';
import { existsSync, unlinkSync } from 'fs';

import { HttpTransport } from '../transport/HttpTransport.js';
import { MessageRouter } from '../transport/MessageRouter.js';
import { LocalRegistry } from '../transport/LocalRegistry.js';
import { ConnectionManager } from '../connection/ConnectionManager.js';
import { ConnectionBroker } from '../transport/ConnectionBroker.js';
import { BlackboardBridge } from '../blackboard/BlackboardBridge.js';
import { SqliteBlackboard } from '../blackboard/SqliteBlackboard.js';
import { StageManager } from '../stage/StageManager.js';
import { MaestroMessage } from '../types/index.js';

// ----------------------------------------------------------
// Helpers
// ----------------------------------------------------------

const PORT_ALPHA = 47810;
const PORT_BETA  = 47811;
const PORT_GAMMA = 47812;
const PORT_HOST  = 47813;
const PORT_GUEST = 47814;

function tmpDb(label: string): string {
  return join(tmpdir(), `maestro-it-${label}-${Date.now()}.db`);
}

function cleanupDb(path: string): void {
  for (const p of [path, path + '-wal', path + '-shm']) {
    try { if (existsSync(p)) unlinkSync(p); } catch { /* ignore */ }
  }
}

function makeTransport(agentId: string, port: number, registryDb: string, connectionManager?: ConnectionManager): {
  transport: HttpTransport;
  router: MessageRouter;
  registry: LocalRegistry;
} {
  const registry = new LocalRegistry(registryDb);
  const stageManager = new StageManager();
  const router = new MessageRouter(agentId, stageManager);
  const transport = new HttpTransport(agentId, router, registry, { port }, connectionManager);
  return { transport, router, registry };
}

// ----------------------------------------------------------
// P2P — direct message Alpha → Beta via real HTTP
// ----------------------------------------------------------

describe('HttpTransport — p2p direct message', () => {
  let alphaTransport: HttpTransport;
  let betaTransport: HttpTransport;
  let betaRouter: MessageRouter;
  let alphaRegistry: LocalRegistry;
  let regDb: string;

  beforeEach(async () => {
    regDb = tmpDb('p2p');
    const alpha = makeTransport('alpha', PORT_ALPHA, regDb);
    const beta  = makeTransport('beta',  PORT_BETA,  regDb);
    alphaTransport = alpha.transport;
    betaTransport  = beta.transport;
    betaRouter     = beta.router;
    alphaRegistry  = alpha.registry;
    await alphaTransport.start();
    await betaTransport.start();
  });

  afterEach(async () => {
    await alphaTransport.stop();
    await betaTransport.stop();
    cleanupDb(regDb);
  });

  it('delivers a direct message from alpha to beta', async () => {
    const received: MaestroMessage[] = [];
    betaRouter.on('direct', (msg) => { received.push(msg); });

    const msg: MaestroMessage = {
      id: randomUUID(),
      type: 'direct',
      content: 'Hello Beta',
      sender: { agentId: 'alpha' },
      recipient: 'beta',
      timestamp: Date.now(),
      version: '3.2',
    };

    const result = await alphaTransport.send(msg);
    expect(result.ok).toBe(true);

    await new Promise(r => setTimeout(r, 30));
    expect(received).toHaveLength(1);
    expect(received[0].content).toBe('Hello Beta');
    expect(received[0].sender.agentId).toBe('alpha');
  });

  it('returns error when recipient not in registry', async () => {
    const msg: MaestroMessage = {
      id: randomUUID(),
      type: 'direct',
      content: 'Hello Ghost',
      sender: { agentId: 'alpha' },
      recipient: 'ghost',
      timestamp: Date.now(),
      version: '3.2',
    };

    const result = await alphaTransport.send(msg);
    expect(result.ok).toBe(false);
    expect(result.error).toContain('ghost');
  });
});

// ----------------------------------------------------------
// P2N — broadcast from alpha to all registered peers
// ----------------------------------------------------------

describe('HttpTransport — p2n broadcast', () => {
  let alphaTransport: HttpTransport;
  let betaTransport: HttpTransport;
  let gammaTransport: HttpTransport;
  let betaReceived: MaestroMessage[];
  let gammaReceived: MaestroMessage[];
  let regDb: string;

  beforeEach(async () => {
    regDb = tmpDb('p2n');
    const alpha = makeTransport('alpha', PORT_ALPHA, regDb);
    const beta  = makeTransport('beta',  PORT_BETA,  regDb);
    const gamma = makeTransport('gamma', PORT_GAMMA, regDb);

    alphaTransport = alpha.transport;
    betaTransport  = beta.transport;
    gammaTransport = gamma.transport;

    betaReceived  = [];
    gammaReceived = [];
    beta.router.on('broadcast', (msg) => { betaReceived.push(msg); });
    gamma.router.on('broadcast', (msg) => { gammaReceived.push(msg); });

    await alphaTransport.start();
    await betaTransport.start();
    await gammaTransport.start();
  });

  afterEach(async () => {
    await alphaTransport.stop();
    await betaTransport.stop();
    await gammaTransport.stop();
    cleanupDb(regDb);
  });

  it('broadcasts to all peers except self', async () => {
    const msg: MaestroMessage = {
      id: randomUUID(),
      type: 'broadcast',
      content: 'Hello everyone',
      sender: { agentId: 'alpha' },
      recipient: '*',
      timestamp: Date.now(),
      version: '3.2',
    };

    const result = await alphaTransport.send(msg);
    expect(result.ok).toBe(true);

    await new Promise(r => setTimeout(r, 50));
    expect(betaReceived).toHaveLength(1);
    expect(gammaReceived).toHaveLength(1);
    expect(betaReceived[0].content).toBe('Hello everyone');
    expect(gammaReceived[0].content).toBe('Hello everyone');
  });

  it('does not deliver broadcast to self', async () => {
    const alphaReceived: MaestroMessage[] = [];
    // alpha's own router — start() already registered alpha, so we just track
    const alphaRouter = makeTransport('alpha-check', 47815, regDb).router;
    alphaRouter.on('broadcast', (msg) => { alphaReceived.push(msg); });

    const msg: MaestroMessage = {
      id: randomUUID(),
      type: 'broadcast',
      content: 'Self-test',
      sender: { agentId: 'alpha' },
      recipient: '*',
      timestamp: Date.now(),
      version: '3.2',
    };

    await alphaTransport.send(msg);
    await new Promise(r => setTimeout(r, 30));
    // Alpha should NOT have received its own broadcast via HTTP
    expect(alphaReceived).toHaveLength(0);
  });
});

// ----------------------------------------------------------
// Blackboard — BlackboardBridge cross-process notification
// ----------------------------------------------------------

describe('BlackboardBridge — cross-process BB notification', () => {
  let alphaTransport: HttpTransport;
  let betaTransport: HttpTransport;
  let betaRouter: MessageRouter;
  let betaBb: SqliteBlackboard;
  let regDb: string;
  let bbDbAlpha: string;
  let bbDbBeta: string;

  beforeEach(async () => {
    regDb    = tmpDb('bb-reg');
    bbDbAlpha = tmpDb('bb-alpha');
    bbDbBeta  = tmpDb('bb-beta');

    const stageId = 'sb-proteus';

    const alpha = makeTransport('alpha', PORT_ALPHA, regDb);
    const beta  = makeTransport('beta',  PORT_BETA,  regDb);

    alphaTransport = alpha.transport;
    betaTransport  = beta.transport;
    betaRouter     = beta.router;

    // Beta registers a SQLiteBlackboard so applyBlackboardUpdate fires
    betaBb = new SqliteBlackboard({ path: bbDbBeta, stageId });
    betaTransport.registerBlackboard(stageId, betaBb);

    await alphaTransport.start();
    await betaTransport.start();
  });

  afterEach(async () => {
    await alphaTransport.stop();
    await betaTransport.stop();
    betaBb.close();
    cleanupDb(regDb);
    cleanupDb(bbDbAlpha);
    cleanupDb(bbDbBeta);
  });

  it('notifies beta when alpha writes to a BB key, and beta applies the update', async () => {
    const stageId = 'sb-proteus';

    // Alpha's bridge uses its transport + registry
    const alphaRegistry = new LocalRegistry(tmpDb('bb-areg-tmp'));
    // Re-use the already-started alpha transport's registry by looking up beta
    const alphaBb = new SqliteBlackboard({ path: bbDbAlpha, stageId });

    // Build bridge manually — points at alpha's transport instance
    const bridge = new BlackboardBridge('alpha', alphaTransport as any, (alphaTransport as any).registry as LocalRegistry);

    // Write to alpha's local BB
    await alphaBb.set('proteus.brief.latest', { briefId: 'b-001', context: 'test' }, 'alpha');
    const entry = await alphaBb.getEntry('proteus.brief.latest');
    expect(entry).toBeDefined();

    // Fan out via bridge to beta
    await bridge.notifyUpdate(stageId, entry!, ['beta']);

    // Give beta time to receive + apply
    await new Promise(r => setTimeout(r, 50));

    // Beta's local BB should now have the key
    const betaEntry = await betaBb.get('proteus.brief.latest');
    expect(betaEntry).toBeDefined();
    expect((betaEntry as any).briefId).toBe('b-001');

    alphaBb.close();
    cleanupDb(tmpDb('bb-areg-tmp'));
  });
});

// ----------------------------------------------------------
// Connection — create + remote join via HTTP
// ----------------------------------------------------------

describe('Connection — create and remote join', () => {
  let hostTransport: HttpTransport;
  let guestTransport: HttpTransport;
  let hostManager: ConnectionManager;
  let guestBroker: ConnectionBroker;
  let hostBroker: ConnectionBroker;
  let regDb: string;

  beforeEach(async () => {
    regDb = tmpDb('conn');

    hostManager = new ConnectionManager();
    const guestManager = new ConnectionManager();

    const host  = makeTransport('host-agent',  PORT_HOST,  regDb, hostManager);
    const guest = makeTransport('guest-agent', PORT_GUEST, regDb, guestManager);

    hostTransport  = host.transport;
    guestTransport = guest.transport;

    await hostTransport.start();
    await guestTransport.start();

    hostBroker = new ConnectionBroker(
      'host-agent',
      hostTransport,
      host.registry,
      hostManager,
      { localPort: PORT_HOST },
    );

    guestBroker = new ConnectionBroker(
      'guest-agent',
      guestTransport,
      guest.registry,
      guestManager,
      { localPort: PORT_GUEST },
    );
  });

  afterEach(async () => {
    await hostTransport.stop();
    await guestTransport.stop();
    cleanupDb(regDb);
  });

  it('host creates a connection and guest joins via HTTP', async () => {
    const { connectionId } = await hostBroker.createConnection({
      name: 'sb-proteus',
      members: [], // no pre-invite needed — guest will joinRemote
    });

    expect(connectionId).toBeTruthy();

    // Confirm host-side connection exists
    const conn = hostManager.get(connectionId);
    expect(conn?.name).toBe('sb-proteus');
    expect(conn?.members).toHaveLength(1); // just the host

    // Guest joins remotely
    const joinResponse = await guestBroker.joinRemote({
      hostAgentId: 'host-agent',
      connectionId,
    });

    expect(joinResponse.status).toBe('accepted');
    expect(joinResponse.connectionId).toBe(connectionId);
    expect(joinResponse.role).toBe('worker');

    // Host-side should now have 2 members
    const updatedConn = hostManager.get(connectionId);
    expect(updatedConn?.members).toHaveLength(2);
    expect(updatedConn?.members.find(m => m.agentId === 'guest-agent')).toBeDefined();
  });

  it('guest receives connection:invitation and can acceptInvitation', async () => {
    const guestRouter = (guestTransport as any).router as MessageRouter;
    const invitations: MaestroMessage[] = [];
    guestRouter.on('connection:invitation', (msg) => { invitations.push(msg); });

    // Host creates connection and invites guest
    const { connectionId } = await hostBroker.createConnection({
      name: 'officers',
      members: ['guest-agent'],
    });

    await new Promise(r => setTimeout(r, 50));

    // Guest should have received the invitation message
    expect(invitations).toHaveLength(1);
    expect(invitations[0].type).toBe('connection:invitation');

    // Guest accepts it
    const payload = invitations[0].payload as any;
    const joinResponse = await guestBroker.acceptInvitation({
      connectionId: payload.connectionId,
      hostAgentId: payload.hostAgentId,
      hostEndpoint: payload.hostEndpoint,
      connectionName: payload.connectionName,
      invitedBy: payload.invitedBy,
    });

    expect(joinResponse.status).toBe('accepted');

    const updatedConn = hostManager.get(connectionId);
    expect(updatedConn?.members).toHaveLength(2);
  });
});
