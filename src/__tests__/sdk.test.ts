// ============================================================
// SDK Integration Tests
// Full end-to-end flows using the Maestro SDK
// ============================================================

import { Maestro } from '../sdk/Maestro.js';
import { MaestroMessage, MessageType } from '../types/index.js';

// ----------------------------------------------------------
// Helpers
// ----------------------------------------------------------

function makeMaestro(agentId: string): Maestro {
  return new Maestro({ agentId });
}

// ----------------------------------------------------------
// Basic SDK tests
// ----------------------------------------------------------

describe('Maestro SDK - setup', () => {
  it('initialises with agentId', () => {
    const m = makeMaestro('Alpha');
    expect(m.agentId).toBe('Alpha');
  });

  it('starts without error', async () => {
    const m = makeMaestro('Alpha');
    await expect(m.start()).resolves.not.toThrow();
  });

  it('is idempotent on start', async () => {
    const m = makeMaestro('Alpha');
    await m.start();
    await expect(m.start()).resolves.not.toThrow();
  });
});

describe('Maestro SDK - Connection creation', () => {
  it('creates an open Connection', () => {
    const m = makeMaestro('Alpha');
    const connection = m.openConnection('Test Room');
    expect(connection.connectionId).toBeTruthy();
    expect(connection.getConnectionInfo().name).toBe('Test Room');
    expect(connection.getConnectionInfo().hostId).toBe('Alpha');
  });

  it('creates a hierarchical Connection', () => {
    const m = makeMaestro('Alpha');
    const connection = m.openHierarchicalConnection(
      'Task Connection',
      ['lead', 'worker'],
      { worker: 'lead' },
    );
    const info = connection.getConnectionInfo();
    expect(info.rules.hierarchy?.roles).toContain('lead');
    expect(info.rules.hierarchy?.roles).toContain('worker');
  });

  it('host is a member with lead role', () => {
    const m = makeMaestro('Alpha');
    const connection = m.openConnection('Room');
    const member = connection.getMember('Alpha');
    expect(member?.role).toBe('lead');
  });
});

describe('Maestro SDK - joining Connections', () => {
  it('joins an open Connection', () => {
    const host = makeMaestro('Alpha');
    const guest = makeMaestro('Beta');

    const connection = host.openConnection('Open Room');
    const response = guest.join(connection.connectionId, host.connectionManager);

    expect(response.status).toBe('accepted');
    expect(response.role).toBe('worker');
  });

  it('gets a ConnectionHandle after joining', () => {
    const host = makeMaestro('Alpha');
    const guest = makeMaestro('Beta');

    const hostConnection = host.openConnection('Room');
    guest.join(hostConnection.connectionId, host.connectionManager);

    const guestConnection = guest.getConnection(hostConnection.connectionId);
    expect(guestConnection).toBeDefined();
    expect(guestConnection?.connectionId).toBe(hostConnection.connectionId);
  });

  it('rejects join to unknown connection', () => {
    const m = makeMaestro('Alpha');
    const response = m.join('nonexistent-connection-id', m.connectionManager);
    expect(response.status).toBe('rejected');
  });
});

describe('Maestro SDK - messaging', () => {
  it('builds a direct message', async () => {
    const host = makeMaestro('Alpha');
    const connection = host.openConnection('Room');

    const msg = await connection.send('Beta', 'Hello Beta');
    expect(msg.type).toBe('direct');
    expect(msg.content).toBe('Hello Beta');
    expect(msg.sender.agentId).toBe('Alpha');
    expect(msg.recipient).toBe('Beta');
    expect(msg.stageId).toBe(connection.connectionId);
  });

  it('builds a broadcast message', async () => {
    const host = makeMaestro('Alpha');
    const connection = host.openConnection('Room');

    const msg = await connection.broadcast('Hello everyone');
    expect(msg.type).toBe('broadcast');
    expect(msg.recipient).toBe('*');
  });

  it('dispatches inbound message to handler', async () => {
    const host = makeMaestro('Alpha');
    const guest = makeMaestro('Beta');
    const hostConnection = host.openConnection('Room');
    guest.join(hostConnection.connectionId, host.connectionManager);

    const received: MaestroMessage[] = [];
    host.onMessage('direct' as MessageType, (msg) => { received.push(msg); });

    const msg = await guest.getConnection(hostConnection.connectionId)!.send('Alpha', 'Hey Alpha');
    await host.receive(msg);

    expect(received).toHaveLength(1);
    expect(received[0].content).toBe('Hey Alpha');
  });

  it('dispatches to wildcard handler', async () => {
    const host = makeMaestro('Alpha');
    const connection = host.openConnection('Room');

    const received: MaestroMessage[] = [];
    host.onMessage('*', (msg) => { received.push(msg); });

    const msg = await connection.send('Beta', 'test');
    await host.receive(msg);

    expect(received.length).toBeGreaterThan(0);
  });
});

describe('Maestro SDK - hierarchy messaging', () => {
  it('reportTo sends to supervisor', async () => {
    const lead = makeMaestro('Lex');
    const worker = makeMaestro('Yuma');

    // Use open entry mode so workers can join without a token
    const connection = lead.createConnection({
      name: 'Task A',
      rules: {
        entryMode: 'open',
        memberVisibility: 'hierarchy',
        hierarchy: { roles: ['lead', 'worker'], reportingChain: { worker: 'lead' }, defaultRole: 'worker' },
        permissions: {
          lead: ['message:send', 'message:broadcast', 'blackboard:read', 'blackboard:write', 'member:invite', 'member:remove', 'role:assign', 'venue:close', 'venue:transfer'],
          worker: ['message:send', 'blackboard:read', 'blackboard:write'],
        },
      },
    });

    worker.join(connection.connectionId, lead.connectionManager);

    const yumaConnection = worker.getConnection(connection.connectionId)!;
    const msg = await yumaConnection.reportTo('Frontend complete');

    expect(msg.type).toBe('report');
    expect(msg.recipient).toBe('Lex');
  });

  it('assignTo sends to subordinate', async () => {
    const lead = makeMaestro('Lex');
    const worker = makeMaestro('Yuma');

    const connection = lead.createConnection({
      name: 'Task A',
      rules: {
        entryMode: 'open',
        memberVisibility: 'all',
        hierarchy: { roles: ['lead', 'worker'], reportingChain: { worker: 'lead' }, defaultRole: 'worker' },
        permissions: {
          lead: ['message:send', 'message:broadcast', 'blackboard:read', 'blackboard:write', 'member:invite', 'member:remove', 'role:assign', 'venue:close', 'venue:transfer'],
          worker: ['message:send', 'blackboard:read', 'blackboard:write'],
        },
      },
    });
    worker.join(connection.connectionId, lead.connectionManager);

    const lexConnection = lead.getConnection(connection.connectionId)!;
    const msg = await lexConnection.assignTo('Yuma', 'Build the frontend');

    expect(msg.type).toBe('assign');
    expect(msg.recipient).toBe('Yuma');
  });

  it('reportTo throws without supervisor', async () => {
    const lead = makeMaestro('Lex');
    const connection = lead.openConnection('Flat Room'); // no hierarchy
    await expect(connection.reportTo('Done')).rejects.toThrow('No supervisor');
  });
});

describe('Maestro SDK - Blackboard', () => {
  it('sets and gets via ConnectionHandle', async () => {
    const m = makeMaestro('Alpha');
    const connection = m.openConnection('Room');

    await connection.blackboard.set('status', { phase: 'design' }, 'Alpha');
    expect(await connection.blackboard.get('status')).toEqual({ phase: 'design' });
  });

  it('different connections have isolated blackboards', async () => {
    const m = makeMaestro('Alpha');
    const s1 = m.openConnection('Room 1');
    const s2 = m.openConnection('Room 2');

    await s1.blackboard.set('key', 'room1-value', 'Alpha');
    expect(await s2.blackboard.get('key')).toBeUndefined();
  });

  it('subscribeAll fires on any write', async () => {
    const m = makeMaestro('Alpha');
    const connection = m.openConnection('Room');

    const keys: string[] = [];
    connection.blackboard.subscribeAll((entry) => keys.push(entry.key));

    await connection.blackboard.set('a', 1, 'Alpha');
    await connection.blackboard.set('b', 2, 'Alpha');

    expect(keys).toContain('a');
    expect(keys).toContain('b');
  });
});

describe('Maestro SDK - Connection lifecycle', () => {
  it('closes a Connection', async () => {
    const m = makeMaestro('Alpha');
    const connection = m.openConnection('Room');
    const connectionId = connection.connectionId;

    await connection.close();

    expect(m.getConnection(connectionId)).toBeUndefined();
    expect(m.connectionManager.get(connectionId)?.status).toBe('closed');
  });

  it('guest can leave Connection', async () => {
    const host = makeMaestro('Alpha');
    const guest = makeMaestro('Beta');
    const hostConnection = host.openConnection('Room');
    guest.join(hostConnection.connectionId, host.connectionManager);

    const guestConnection = guest.getConnection(hostConnection.connectionId)!;
    await guestConnection.leave();

    expect(guest.getConnection(hostConnection.connectionId)).toBeUndefined();
    expect(host.connectionManager.getMember(hostConnection.connectionId, 'Beta')).toBeUndefined();
  });

  it('lists all connections', () => {
    const m = makeMaestro('Alpha');
    m.openConnection('Room 1');
    m.openConnection('Room 2');
    expect(m.listConnections()).toHaveLength(2);
  });
});

describe('Maestro SDK - provenance policy enforcement', () => {
  it('rejects message missing required provenance', async () => {
    const m = makeMaestro('Alpha');
    const connection = m.createConnection({
      name: 'Secure Connection',
      rules: {
        entryMode: 'open',
        memberVisibility: 'all',
        permissions: { lead: ['message:send', 'message:broadcast', 'blackboard:read', 'blackboard:write', 'member:invite', 'member:remove', 'role:assign', 'venue:close', 'venue:transfer'], worker: ['message:send', 'blackboard:read', 'blackboard:write'] },
        provenancePolicy: {
          requiredFor: ['capability'],
        },
      },
    });

    const msg: MaestroMessage = {
      id: '1',
      type: 'capability',
      content: 'use hieroglyphics',
      sender: { agentId: 'Beta' },
      recipient: 'Alpha',
      timestamp: Date.now(),
      stageId: connection.connectionId,
      version: '3.2',
    };

    const result = await m.receive(msg);
    expect(result.accepted).toBe(false);
    expect(result.reason).toContain('provenance_required');
  });

  it('accepts message with provenance when required', async () => {
    const m = makeMaestro('Alpha');
    const connection = m.createConnection({
      name: 'Secure Connection',
      rules: {
        entryMode: 'open',
        memberVisibility: 'all',
        permissions: { lead: ['message:send', 'message:broadcast', 'blackboard:read', 'blackboard:write', 'member:invite', 'member:remove', 'role:assign', 'venue:close', 'venue:transfer'], worker: ['message:send', 'blackboard:read', 'blackboard:write'] },
        provenancePolicy: { requiredFor: ['capability'] },
      },
    });

    const msg: MaestroMessage = {
      id: '2',
      type: 'capability',
      content: 'use good crypto',
      sender: { agentId: 'Beta' },
      recipient: 'Alpha',
      timestamp: Date.now(),
      stageId: connection.connectionId,
      version: '3.2',
      provenance: {
        mode: 'full',
        chain: [],
        originalSignature: 'sig',
        contentHash: 'hash',
      },
    };

    const result = await m.receive(msg);
    expect(result.accepted).toBe(true);
  });
});
