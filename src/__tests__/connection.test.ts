import { ConnectionManager, DEFAULT_PERMISSIONS } from '../connection/ConnectionManager.js';
import { enforceProvenancePolicy } from '../connection/provenanceEnforcer.js';
import { CreateConnectionRequest, ConnectionRules } from '../connection/types.js';
import { MaestroMessage } from '../types/index.js';

// ----------------------------------------------------------
// Helpers
// ----------------------------------------------------------

function makeRules(overrides: Partial<ConnectionRules> = {}): ConnectionRules {
  return {
    entryMode: 'open',
    memberVisibility: 'all',
    permissions: {
      lead: [...DEFAULT_PERMISSIONS.lead],
      worker: [...DEFAULT_PERMISSIONS.worker],
    },
    ...overrides,
  };
}

function makeCreateRequest(overrides: Partial<CreateConnectionRequest> = {}): CreateConnectionRequest {
  return {
    name: 'Test Connection',
    rules: makeRules(),
    ...overrides,
  };
}

// ----------------------------------------------------------
// ConnectionManager tests
// ----------------------------------------------------------

describe('ConnectionManager - creation', () => {
  it('creates a connection with host as lead', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(makeCreateRequest(), 'Alpha');

    expect(connection.id).toBeTruthy();
    expect(connection.hostId).toBe('Alpha');
    expect(connection.members).toHaveLength(1);
    expect(connection.members[0].agentId).toBe('Alpha');
    expect(connection.members[0].role).toBe('lead');
  });

  it('creates with initial members', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(
      makeCreateRequest({
        initialMembers: [
          { agentId: 'Beta', role: 'worker' },
          { agentId: 'Gamma', role: 'worker' },
        ],
      }),
      'Alpha',
    );

    expect(connection.members).toHaveLength(3);
    expect(connection.status).toBe('active');
  });

  it('wires hierarchy on creation', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(
      makeCreateRequest({
        rules: makeRules({
          hierarchy: {
            roles: ['lead', 'worker'],
            reportingChain: { worker: 'lead' },
            defaultRole: 'worker',
          },
        }),
        initialMembers: [{ agentId: 'Beta', role: 'worker' }],
      }),
      'Alpha',
    );

    const beta = connection.members.find(m => m.agentId === 'Beta');
    const alpha = connection.members.find(m => m.agentId === 'Alpha');
    expect(beta?.supervisorId).toBe('Alpha');
    expect(alpha?.subordinateIds).toContain('Beta');
  });
});

describe('ConnectionManager - joining', () => {
  it('accepts join to open connection', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(makeCreateRequest(), 'Alpha');

    const result = mgr.processJoin(connection.id, {
      protocolVersion: '3.2',
      agentId: 'Beta',
      identity: {},
      webhookEndpoint: 'http://beta.local/webhook',
    });

    expect(result.status).toBe('accepted');
    expect(result.role).toBe('worker');
  });

  it('rejects join without invite token for invitation-mode connection', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(makeCreateRequest({ rules: makeRules({ entryMode: 'invitation' }) }), 'Alpha');

    const result = mgr.processJoin(connection.id, {
      protocolVersion: '3.2',
      agentId: 'Beta',
      identity: {},
      webhookEndpoint: 'http://beta.local/webhook',
    });

    expect(result.status).toBe('rejected');
    expect(result.reason).toBe('invite_required');
  });

  it('accepts join with invite token for invitation-mode connection', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(makeCreateRequest({ rules: makeRules({ entryMode: 'invitation' }) }), 'Alpha');

    const result = mgr.processJoin(connection.id, {
      protocolVersion: '3.2',
      agentId: 'Beta',
      identity: {},
      webhookEndpoint: 'http://beta.local/webhook',
      inviteToken: 'some-token',
    });

    expect(result.status).toBe('accepted');
  });

  it('returns pending for approval-mode connection', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(makeCreateRequest({ rules: makeRules({ entryMode: 'approval' }) }), 'Alpha');

    const result = mgr.processJoin(connection.id, {
      protocolVersion: '3.2',
      agentId: 'Beta',
      identity: {},
      webhookEndpoint: 'http://beta.local/webhook',
    });

    expect(result.status).toBe('pending');
    expect(result.requestId).toBeTruthy();
  });

  it('rejects join to closed connection', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(makeCreateRequest(), 'Alpha');
    mgr.close(connection.id, 'Alpha');

    const result = mgr.processJoin(connection.id, {
      protocolVersion: '3.2',
      agentId: 'Beta',
      identity: {},
      webhookEndpoint: 'http://beta.local/webhook',
    });

    expect(result.status).toBe('rejected');
    expect(result.reason).toBe('venue_closed');
  });

  it('rejects join when connection is full', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(
      makeCreateRequest({ rules: makeRules({ maxMembers: 2 }) }),
      'Alpha',
    );

    mgr.processJoin(connection.id, { protocolVersion: '3.2', agentId: 'Beta', identity: {}, webhookEndpoint: '' });
    const result = mgr.processJoin(connection.id, { protocolVersion: '3.2', agentId: 'Gamma', identity: {}, webhookEndpoint: '' });

    expect(result.status).toBe('rejected');
    expect(result.reason).toBe('venue_full');
  });

  it('rejects duplicate join', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(makeCreateRequest(), 'Alpha');

    mgr.processJoin(connection.id, { protocolVersion: '3.2', agentId: 'Beta', identity: {}, webhookEndpoint: '' });
    const result = mgr.processJoin(connection.id, { protocolVersion: '3.2', agentId: 'Beta', identity: {}, webhookEndpoint: '' });

    expect(result.status).toBe('rejected');
    expect(result.reason).toBe('already_member');
  });
});

describe('ConnectionManager - permissions', () => {
  it('allows permitted action', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(makeCreateRequest(), 'Alpha');
    const result = mgr.checkPermission(connection.id, 'Alpha', 'venue:close');
    expect(result.allowed).toBe(true);
  });

  it('denies unpermitted action', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(makeCreateRequest(), 'Alpha');
    mgr.processJoin(connection.id, { protocolVersion: '3.2', agentId: 'Beta', identity: {}, webhookEndpoint: '' });
    const result = mgr.checkPermission(connection.id, 'Beta', 'venue:close');
    expect(result.allowed).toBe(false);
  });

  it('denies non-member', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(makeCreateRequest(), 'Alpha');
    const result = mgr.checkPermission(connection.id, 'Stranger', 'message:send');
    expect(result.allowed).toBe(false);
    expect(result.reason).toBe('not_a_member');
  });

  it('requirePermission throws on denial', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(makeCreateRequest(), 'Alpha');
    mgr.processJoin(connection.id, { protocolVersion: '3.2', agentId: 'Beta', identity: {}, webhookEndpoint: '' });
    expect(() => mgr.requirePermission(connection.id, 'Beta', 'venue:close')).toThrow();
  });
});

describe('ConnectionManager - role management', () => {
  it('assigns a role', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(
      makeCreateRequest({
        rules: makeRules({
          hierarchy: {
            roles: ['lead', 'worker', 'observer'],
            reportingChain: { worker: 'lead', observer: 'lead' },
            defaultRole: 'worker',
          },
          permissions: {
            lead: [...DEFAULT_PERMISSIONS.lead],
            worker: [...DEFAULT_PERMISSIONS.worker],
            observer: [...DEFAULT_PERMISSIONS.observer],
          },
        }),
      }),
      'Alpha',
    );

    mgr.processJoin(connection.id, { protocolVersion: '3.2', agentId: 'Beta', identity: {}, webhookEndpoint: '' });
    mgr.assignRole(connection.id, 'Alpha', 'Beta', 'observer');

    const beta = mgr.getMember(connection.id, 'Beta');
    expect(beta?.role).toBe('observer');
  });

  it('transfers lead role', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(makeCreateRequest(), 'Alpha');
    mgr.processJoin(connection.id, { protocolVersion: '3.2', agentId: 'Beta', identity: {}, webhookEndpoint: '' });

    mgr.transferRole(connection.id, 'Alpha', { role: 'lead', to: 'Beta' });

    const beta = mgr.getMember(connection.id, 'Beta');
    const alpha = mgr.getMember(connection.id, 'Alpha');
    expect(beta?.role).toBe('lead');
    expect(alpha?.role).toBe('worker');
  });

  it('removes a member', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(makeCreateRequest(), 'Alpha');
    mgr.processJoin(connection.id, { protocolVersion: '3.2', agentId: 'Beta', identity: {}, webhookEndpoint: '' });

    mgr.removeMember(connection.id, 'Alpha', 'Beta');
    expect(mgr.getMember(connection.id, 'Beta')).toBeUndefined();
  });
});

describe('ConnectionManager - visibility', () => {
  it('all visibility shows all members', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(makeCreateRequest(), 'Alpha');
    mgr.processJoin(connection.id, { protocolVersion: '3.2', agentId: 'Beta', identity: {}, webhookEndpoint: '' });
    mgr.processJoin(connection.id, { protocolVersion: '3.2', agentId: 'Gamma', identity: {}, webhookEndpoint: '' });

    const visible = mgr.visibleMembers(connection, 'Beta');
    expect(visible.map(m => m.agentId)).toContain('Alpha');
    expect(visible.map(m => m.agentId)).toContain('Gamma');
  });

  it('hierarchy visibility shows supervisor and peers only', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(
      makeCreateRequest({
        rules: makeRules({
          memberVisibility: 'hierarchy',
          hierarchy: {
            roles: ['lead', 'worker'],
            reportingChain: { worker: 'lead' },
            defaultRole: 'worker',
          },
        }),
        initialMembers: [
          { agentId: 'Beta', role: 'worker' },
          { agentId: 'Gamma', role: 'worker' },
        ],
      }),
      'Alpha',
    );

    const betaVisible = mgr.visibleMembers(mgr.get(connection.id)!, 'Beta');
    const ids = betaVisible.map(m => m.agentId);
    expect(ids).toContain('Alpha'); // supervisor
    expect(ids).toContain('Gamma'); // peer
    expect(ids).toContain('Beta');  // self
  });
});

describe('ConnectionManager - lifecycle', () => {
  it('closes a connection', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(makeCreateRequest(), 'Alpha');
    mgr.close(connection.id, 'Alpha');
    expect(mgr.get(connection.id)?.status).toBe('closed');
  });

  it('prunes expired connections', () => {
    const mgr = new ConnectionManager();
    const connection = mgr.create(makeCreateRequest({ expiresAt: Date.now() - 1000 }), 'Alpha');
    const pruned = mgr.pruneExpired();
    expect(pruned).toContain(connection.id);
    expect(mgr.get(connection.id)?.status).toBe('closed');
  });
});

// ----------------------------------------------------------
// Provenance policy enforcer tests
// ----------------------------------------------------------

describe('enforceProvenancePolicy', () => {
  function makeMsg(overrides: Partial<MaestroMessage> = {}): MaestroMessage {
    return {
      id: '1',
      type: 'capability',
      content: 'test',
      sender: { agentId: 'Alpha' },
      recipient: 'Beta',
      timestamp: 1000,
      version: '3.2',
      ...overrides,
    };
  }

  it('accepts message with no policy restrictions', () => {
    const result = enforceProvenancePolicy(makeMsg(), {});
    expect(result.accepted).toBe(true);
  });

  it('rejects message missing required provenance', () => {
    const result = enforceProvenancePolicy(
      makeMsg({ type: 'capability' }),
      { requiredFor: ['capability'] },
    );
    expect(result.accepted).toBe(false);
    expect(result.reason).toContain('provenance_required');
  });

  it('rejects truncated provenance when not allowed', () => {
    const result = enforceProvenancePolicy(
      makeMsg({
        provenance: {
          mode: 'bookends',
          truncatedChain: {
            mode: 'bookends',
            recentHops: [],
            hiddenMiddleCount: 2,
            fullChainHash: 'abc',
            truncatedAt: 1000,
          },
          originalSignature: 'sig',
          contentHash: 'hash',
        },
      }),
      { allowTruncated: false },
    );
    expect(result.accepted).toBe(false);
    expect(result.reason).toBe('truncated_provenance_not_allowed');
  });

  it('rejects mode below minimum', () => {
    const result = enforceProvenancePolicy(
      makeMsg({
        provenance: {
          mode: 'tail-only',
          truncatedChain: {
            mode: 'tail-only',
            recentHops: [],
            hiddenMiddleCount: 5,
            fullChainHash: 'abc',
            truncatedAt: 1000,
          },
          originalSignature: 'sig',
          contentHash: 'hash',
        },
      }),
      { minimumTruncationMode: 'bookends' },
    );
    expect(result.accepted).toBe(false);
    expect(result.reason).toContain('below_minimum');
  });

  it('rejects non-full chain when full required for type', () => {
    const result = enforceProvenancePolicy(
      makeMsg({
        type: 'financial',
        provenance: {
          mode: 'bookends',
          truncatedChain: {
            mode: 'bookends',
            recentHops: [],
            hiddenMiddleCount: 1,
            fullChainHash: 'abc',
            truncatedAt: 1000,
          },
          originalSignature: 'sig',
          contentHash: 'hash',
        },
      }),
      { requireFullChainFor: ['financial'] },
    );
    expect(result.accepted).toBe(false);
    expect(result.reason).toContain('full_chain_required');
  });

  it('accepts full chain when required', () => {
    const result = enforceProvenancePolicy(
      makeMsg({
        type: 'financial',
        provenance: {
          mode: 'full',
          chain: [],
          originalSignature: 'sig',
          contentHash: 'hash',
        },
      }),
      { requireFullChainFor: ['financial'] },
    );
    expect(result.accepted).toBe(true);
  });

  it('accepts message without provenance when not required', () => {
    const result = enforceProvenancePolicy(
      makeMsg({ type: 'chat' }),
      { requiredFor: ['capability'] },
    );
    expect(result.accepted).toBe(true);
  });
});
