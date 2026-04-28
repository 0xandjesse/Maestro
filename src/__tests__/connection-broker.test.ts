// ============================================================
// Connection Broker & Connection Store Tests
// ============================================================

import { jest } from '@jest/globals';
import { randomUUID } from 'crypto';
import { unlinkSync, existsSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { ConnectionStore, StoredConnection } from '../transport/ConnectionStore.js';
import { ConnectionBroker, ConnectionInvitation } from '../transport/ConnectionBroker.js';
import { ConnectionManager } from '../connection/ConnectionManager.js';
import { LocalRegistry } from '../transport/LocalRegistry.js';
import { HttpTransport } from '../transport/HttpTransport.js';

// ----------------------------------------------------------
// Helpers
// ----------------------------------------------------------

function tmpDb(): string {
  return join(tmpdir(), `maestro-conn-${Date.now()}-${Math.random().toString(36).slice(2)}.db`);
}

function cleanupDb(dbPath: string, store?: ConnectionStore): void {
  try { store?.destroy(); } catch { /* ignore */ }
  if (existsSync(dbPath)) unlinkSync(dbPath);
  const wal = dbPath + '-wal';
  const shm = dbPath + '-shm';
  if (existsSync(wal)) unlinkSync(wal);
  if (existsSync(shm)) unlinkSync(shm);
}

function sampleConnection(overrides: Partial<StoredConnection> = {}): StoredConnection {
  return {
    connectionId:  randomUUID(),
    name:          'Test Connection',
    hostAgentId:   'host-agent',
    hostEndpoint:  'http://127.0.0.1:4000',
    myRole:        'worker',
    status:        'active',
    joinedAt:      Date.now(),
    ...overrides,
  };
}

// ----------------------------------------------------------
// ConnectionStore - save and retrieve
// ----------------------------------------------------------

describe('ConnectionStore - save and retrieve', () => {
  it('saves and retrieves a connection', () => {
    const dbPath = tmpDb();
    const store = new ConnectionStore(dbPath);
    try {
      const connection = sampleConnection();
      store.save(connection);

      const retrieved = store.get(connection.connectionId);
      expect(retrieved).toBeDefined();
      expect(retrieved?.connectionId).toBe(connection.connectionId);
      expect(retrieved?.name).toBe(connection.name);
      expect(retrieved?.hostAgentId).toBe(connection.hostAgentId);
      expect(retrieved?.myRole).toBe(connection.myRole);
      expect(retrieved?.status).toBe('active');
    } finally {
      cleanupDb(dbPath, store);
    }
  });

  it('returns undefined for unknown connectionId', () => {
    const dbPath = tmpDb();
    const store = new ConnectionStore(dbPath);
    try {
      expect(store.get('nonexistent')).toBeUndefined();
    } finally {
      cleanupDb(dbPath, store);
    }
  });

  it('persists expiresAt when provided', () => {
    const dbPath = tmpDb();
    const store = new ConnectionStore(dbPath);
    try {
      const expiresAt = Date.now() + 60_000;
      const connection = sampleConnection({ expiresAt });
      store.save(connection);
      expect(store.get(connection.connectionId)?.expiresAt).toBe(expiresAt);
    } finally {
      cleanupDb(dbPath, store);
    }
  });

  it('omits expiresAt when not provided', () => {
    const dbPath = tmpDb();
    const store = new ConnectionStore(dbPath);
    try {
      const connection = sampleConnection({ expiresAt: undefined });
      store.save(connection);
      expect(store.get(connection.connectionId)?.expiresAt).toBeUndefined();
    } finally {
      cleanupDb(dbPath, store);
    }
  });
});

// ----------------------------------------------------------
// ConnectionStore - list active connections
// ----------------------------------------------------------

describe('ConnectionStore - list active connections', () => {
  it('lists only active connections', () => {
    const dbPath = tmpDb();
    const store = new ConnectionStore(dbPath);
    try {
      const active = sampleConnection({ status: 'active' });
      const closed = sampleConnection({ status: 'closed' });
      store.save(active);
      store.save(closed);

      const actives = store.listActive();
      expect(actives).toHaveLength(1);
      expect(actives[0].connectionId).toBe(active.connectionId);
    } finally {
      cleanupDb(dbPath, store);
    }
  });

  it('lists all connections regardless of status', () => {
    const dbPath = tmpDb();
    const store = new ConnectionStore(dbPath);
    try {
      store.save(sampleConnection({ status: 'active' }));
      store.save(sampleConnection({ status: 'closed' }));
      expect(store.list()).toHaveLength(2);
    } finally {
      cleanupDb(dbPath, store);
    }
  });
});

// ----------------------------------------------------------
// ConnectionStore - close a connection
// ----------------------------------------------------------

describe('ConnectionStore - close a connection', () => {
  it('marks connection as closed', () => {
    const dbPath = tmpDb();
    const store = new ConnectionStore(dbPath);
    try {
      const connection = sampleConnection({ status: 'active' });
      store.save(connection);
      store.close(connection.connectionId);

      expect(store.get(connection.connectionId)?.status).toBe('closed');
      expect(store.listActive()).toHaveLength(0);
    } finally {
      cleanupDb(dbPath, store);
    }
  });
});

// ----------------------------------------------------------
// ConnectionStore - delete a connection
// ----------------------------------------------------------

describe('ConnectionStore - delete a connection', () => {
  it('removes the connection from the store', () => {
    const dbPath = tmpDb();
    const store = new ConnectionStore(dbPath);
    try {
      const connection = sampleConnection();
      store.save(connection);
      store.delete(connection.connectionId);

      expect(store.get(connection.connectionId)).toBeUndefined();
      expect(store.list()).toHaveLength(0);
    } finally {
      cleanupDb(dbPath, store);
    }
  });
});

// ----------------------------------------------------------
// ConnectionStore - persistence across instantiation
// ----------------------------------------------------------

describe('ConnectionStore - persistence across instantiation', () => {
  it('survives re-opening the same db file', () => {
    const dbPath = tmpDb();
    const connection = sampleConnection();

    const store1 = new ConnectionStore(dbPath);
    store1.save(connection);
    store1.destroy();

    const store2 = new ConnectionStore(dbPath);
    try {
      const retrieved = store2.get(connection.connectionId);
      expect(retrieved?.connectionId).toBe(connection.connectionId);
      expect(retrieved?.name).toBe(connection.name);
      expect(retrieved?.status).toBe('active');
    } finally {
      cleanupDb(dbPath, store2);
    }
  });

  it('close state persists across instantiation', () => {
    const dbPath = tmpDb();
    const connection = sampleConnection({ status: 'active' });

    const store1 = new ConnectionStore(dbPath);
    store1.save(connection);
    store1.close(connection.connectionId);
    store1.destroy();

    const store2 = new ConnectionStore(dbPath);
    try {
      expect(store2.get(connection.connectionId)?.status).toBe('closed');
      expect(store2.listActive()).toHaveLength(0);
    } finally {
      cleanupDb(dbPath, store2);
    }
  });
});

// ----------------------------------------------------------
// ConnectionStore - upsert (save overwrite)
// ----------------------------------------------------------

describe('ConnectionStore - upsert (save overwrite)', () => {
  it('updates an existing connection when saved again', () => {
    const dbPath = tmpDb();
    const store = new ConnectionStore(dbPath);
    try {
      const connection = sampleConnection({ status: 'active' });
      store.save(connection);
      store.save({ ...connection, status: 'closed', myRole: 'lead' });

      const updated = store.get(connection.connectionId);
      expect(updated?.status).toBe('closed');
      expect(updated?.myRole).toBe('lead');
    } finally {
      cleanupDb(dbPath, store);
    }
  });
});

// ----------------------------------------------------------
// ConnectionBroker helpers
// ----------------------------------------------------------

function makeBroker(): {
  broker: ConnectionBroker;
  connectionManager: ConnectionManager;
  registry: LocalRegistry;
  sendMock: ReturnType<typeof jest.fn>;
  registryDb: string;
} {
  const connectionManager = new ConnectionManager();
  const registryDb = tmpDb();
  const registry = new LocalRegistry(registryDb);

  const sendMock = jest.fn<() => Promise<{ ok: boolean }>>().mockResolvedValue({ ok: true });

  const transport = { send: sendMock } as unknown as HttpTransport;

  const broker = new ConnectionBroker(
    'test-agent',
    transport,
    registry,
    connectionManager,
    { localPort: 4242 },
  );

  return { broker, connectionManager, registry, sendMock, registryDb };
}

// ----------------------------------------------------------
// ConnectionBroker - createConnection
// ----------------------------------------------------------

describe('ConnectionBroker - createConnection', () => {
  it('creates a Connection locally and returns connectionId', async () => {
    const { broker, connectionManager } = makeBroker();

    const result = await broker.createConnection({
      name:    'My Connection',
      members: [],
    });

    expect(result.connectionId).toBeTruthy();

    const connection = connectionManager.get(result.connectionId);
    expect(connection).toBeDefined();
    expect(connection?.name).toBe('My Connection');
    expect(connection?.hostId).toBe('test-agent');
  });

  it('sends connection:invitation to each member', async () => {
    const { broker, sendMock } = makeBroker();

    await broker.createConnection({
      name:    'Team Room',
      members: ['agent-a', 'agent-b'],
    });

    expect(sendMock).toHaveBeenCalledTimes(2);

    const firstCall = sendMock.mock.calls[0][0] as Record<string, unknown>;
    expect(firstCall['type']).toBe('connection:invitation');
    expect(firstCall['recipient']).toBe('agent-a');
  });

  it('includes invitation payload with correct fields', async () => {
    const { broker, sendMock } = makeBroker();

    await broker.createConnection({
      name:    'Payload Test',
      members: ['agent-x'],
    });

    const msg = sendMock.mock.calls[0][0] as Record<string, unknown>;
    const payload = msg['payload'] as Record<string, unknown>;
    expect(payload['hostEndpoint']).toBe('http://127.0.0.1:4242');
    expect(payload['connectionName']).toBe('Payload Test');
    expect(payload['hostAgentId']).toBe('test-agent');
  });

  it('does not throw if a member invite delivery fails', async () => {
    const { broker, sendMock } = makeBroker();
    sendMock.mockRejectedValue(new Error('network down'));

    await expect(
      broker.createConnection({ name: 'Room', members: ['unreachable-agent'] }),
    ).resolves.not.toThrow();
  });
});

// ----------------------------------------------------------
// ConnectionBroker - joinRemote
// ----------------------------------------------------------

describe('ConnectionBroker - joinRemote', () => {
  it('returns rejected if host not found in registry', async () => {
    const { broker } = makeBroker();
    const response = await broker.joinRemote({
      hostAgentId:  'unknown-host',
      connectionId: randomUUID(),
    });
    expect(response.status).toBe('rejected');
    expect(response.reason).toBe('host_not_found');
  });

  it('POSTs to the correct /connections/:connectionId/join endpoint', async () => {
    const { broker, registry } = makeBroker();

    registry.register({
      agentId:         'remote-host',
      webhookEndpoint: 'http://192.168.1.50:3842/message',
    });

    const connectionId = randomUUID();

    const mockFetch = jest.fn<typeof fetch>().mockResolvedValue({
      json: async () => ({ status: 'accepted', connectionId, role: 'worker', members: [] }),
    } as unknown as Response);
    global.fetch = mockFetch as unknown as typeof fetch;

    await broker.joinRemote({ hostAgentId: 'remote-host', connectionId });

    expect(mockFetch).toHaveBeenCalledWith(
      `http://192.168.1.50:3842/connections/${connectionId}/join`,
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('returns network_error on fetch failure', async () => {
    const { broker, registry } = makeBroker();

    registry.register({
      agentId:         'remote-host',
      webhookEndpoint: 'http://127.0.0.1:9999/message',
    });

    const mockFetch = jest.fn<typeof fetch>().mockRejectedValue(new Error('ECONNREFUSED'));
    global.fetch = mockFetch as unknown as typeof fetch;

    const response = await broker.joinRemote({
      hostAgentId:  'remote-host',
      connectionId: randomUUID(),
    });

    expect(response.status).toBe('rejected');
    expect(response.reason).toContain('network_error');
  });
});

// ----------------------------------------------------------
// ConnectionBroker - acceptInvitation
// ----------------------------------------------------------

describe('ConnectionBroker - acceptInvitation', () => {
  it('uses hostEndpoint from the invitation to build the URL', async () => {
    const { broker } = makeBroker();
    const connectionId = randomUUID();

    const mockFetch = jest.fn<typeof fetch>().mockResolvedValue({
      json: async () => ({ status: 'accepted', connectionId, role: 'worker', members: [] }),
    } as unknown as Response);
    global.fetch = mockFetch as unknown as typeof fetch;

    const invitation: ConnectionInvitation = {
      connectionId,
      hostAgentId:    'remote-agent',
      hostEndpoint:   'http://10.0.0.5:3842',
      connectionName: 'Test Connection',
      invitedBy:      'remote-agent',
    };

    await broker.acceptInvitation(invitation);

    expect(mockFetch).toHaveBeenCalledWith(
      `http://10.0.0.5:3842/connections/${connectionId}/join`,
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('sends the correct agentId and webhookEndpoint in the join body', async () => {
    const { broker } = makeBroker();
    const connectionId = randomUUID();

    let capturedBody: Record<string, unknown> = {};
    const mockFetch = jest.fn<typeof fetch>().mockImplementation(async (_url, opts) => {
      capturedBody = JSON.parse((opts as RequestInit).body as string);
      return {
        json: async () => ({ status: 'accepted', connectionId, role: 'worker', members: [] }),
      } as unknown as Response;
    });
    global.fetch = mockFetch as unknown as typeof fetch;

    const invitation: ConnectionInvitation = {
      connectionId,
      hostAgentId:    'host',
      hostEndpoint:   'http://10.0.0.5:3842',
      connectionName: 'Test',
      invitedBy:      'host',
    };

    await broker.acceptInvitation(invitation);

    expect(capturedBody['agentId']).toBe('test-agent');
    expect(capturedBody['webhookEndpoint']).toBe('http://127.0.0.1:4242/message');
  });
});
