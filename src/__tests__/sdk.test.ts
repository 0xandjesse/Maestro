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

describe('Maestro SDK — setup', () => {
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

describe('Maestro SDK — Stage creation', () => {
  it('creates an open Stage', () => {
    const m = makeMaestro('Alpha');
    const venue = m.createOpenStage('Test Room');
    expect(venue.stageId).toBeTruthy();
    expect(venue.getStageInfo().name).toBe('Test Room');
    expect(venue.getStageInfo().hostId).toBe('Alpha');
  });

  it('creates a hierarchical Stage', () => {
    const m = makeMaestro('Alpha');
    const venue = m.createHierarchicalStage(
      'Task Stage',
      ['lead', 'worker'],
      { worker: 'lead' },
    );
    const info = venue.getStageInfo();
    expect(info.rules.hierarchy?.roles).toContain('lead');
    expect(info.rules.hierarchy?.roles).toContain('worker');
  });

  it('host is a member with lead role', () => {
    const m = makeMaestro('Alpha');
    const venue = m.createOpenStage('Room');
    const member = venue.getMember('Alpha');
    expect(member?.role).toBe('lead');
  });
});

describe('Maestro SDK — joining Stages', () => {
  it('joins an open Stage', () => {
    const host = makeMaestro('Alpha');
    const guest = makeMaestro('Beta');

    const venue = host.createOpenStage('Open Room');
    const response = guest.join(venue.stageId, host.stageManager);

    expect(response.status).toBe('accepted');
    expect(response.role).toBe('worker');
  });

  it('gets a StageHandle after joining', () => {
    const host = makeMaestro('Alpha');
    const guest = makeMaestro('Beta');

    const hostVenue = host.createOpenStage('Room');
    guest.join(hostVenue.stageId, host.stageManager);

    const guestVenue = guest.getStage(hostVenue.stageId);
    expect(guestVenue).toBeDefined();
    expect(guestVenue?.stageId).toBe(hostVenue.stageId);
  });

  it('rejects join to unknown stage', () => {
    const m = makeMaestro('Alpha');
    const response = m.join('nonexistent-venue-id', m.stageManager);
    expect(response.status).toBe('rejected');
  });
});

describe('Maestro SDK — messaging', () => {
  it('builds a direct message', async () => {
    const host = makeMaestro('Alpha');
    const venue = host.createOpenStage('Room');

    const msg = await venue.send('Beta', 'Hello Beta');
    expect(msg.type).toBe('direct');
    expect(msg.content).toBe('Hello Beta');
    expect(msg.sender.agentId).toBe('Alpha');
    expect(msg.recipient).toBe('Beta');
    expect(msg.stageId).toBe(venue.stageId);
  });

  it('builds a broadcast message', async () => {
    const host = makeMaestro('Alpha');
    const venue = host.createOpenStage('Room');

    const msg = await venue.broadcast('Hello everyone');
    expect(msg.type).toBe('broadcast');
    expect(msg.recipient).toBe('*');
  });

  it('dispatches inbound message to handler', async () => {
    const host = makeMaestro('Alpha');
    const guest = makeMaestro('Beta');
    const hostVenue = host.createOpenStage('Room');
    guest.join(hostVenue.stageId, host.stageManager);

    const received: MaestroMessage[] = [];
    host.onMessage('direct' as MessageType, (msg) => { received.push(msg); });

    const msg = await guest.getStage(hostVenue.stageId)!.send('Alpha', 'Hey Alpha');
    await host.receive(msg);

    expect(received).toHaveLength(1);
    expect(received[0].content).toBe('Hey Alpha');
  });

  it('dispatches to wildcard handler', async () => {
    const host = makeMaestro('Alpha');
    const venue = host.createOpenStage('Room');

    const received: MaestroMessage[] = [];
    host.onMessage('*', (msg) => { received.push(msg); });

    const msg = await venue.send('Beta', 'test');
    await host.receive(msg);

    expect(received.length).toBeGreaterThan(0);
  });
});

describe('Maestro SDK — hierarchy messaging', () => {
  it('reportTo sends to supervisor', async () => {
    const lead = makeMaestro('Lex');
    const worker = makeMaestro('Yuma');

    // Use open entry mode so workers can join without a token
    const venue = lead.createStage({
      name: 'Task A',
      rules: {
        entryMode: 'open',
        memberVisibility: 'hierarchy',
        hierarchy: { roles: ['lead', 'worker'], reportingChain: { worker: 'lead' }, defaultRole: 'worker' },
        permissions: {
          lead: ['message:send', 'message:broadcast', 'blackboard:read', 'blackboard:write', 'member:invite', 'member:remove', 'role:assign', 'stage:close', 'stage:transfer'],
          worker: ['message:send', 'blackboard:read', 'blackboard:write'],
        },
      },
    });

    worker.join(venue.stageId, lead.stageManager);

    const yumavenue = worker.getStage(venue.stageId)!;
    const msg = await yumavenue.reportTo('Frontend complete');

    expect(msg.type).toBe('report');
    expect(msg.recipient).toBe('Lex');
  });

  it('assignTo sends to subordinate', async () => {
    const lead = makeMaestro('Lex');
    const worker = makeMaestro('Yuma');

    const venue = lead.createStage({
      name: 'Task A',
      rules: {
        entryMode: 'open',
        memberVisibility: 'all',
        hierarchy: { roles: ['lead', 'worker'], reportingChain: { worker: 'lead' }, defaultRole: 'worker' },
        permissions: {
          lead: ['message:send', 'message:broadcast', 'blackboard:read', 'blackboard:write', 'member:invite', 'member:remove', 'role:assign', 'stage:close', 'stage:transfer'],
          worker: ['message:send', 'blackboard:read', 'blackboard:write'],
        },
      },
    });
    worker.join(venue.stageId, lead.stageManager);

    const lexVenue = lead.getStage(venue.stageId)!;
    const msg = await lexVenue.assignTo('Yuma', 'Build the frontend');

    expect(msg.type).toBe('assign');
    expect(msg.recipient).toBe('Yuma');
  });

  it('reportTo throws without supervisor', async () => {
    const lead = makeMaestro('Lex');
    const venue = lead.createOpenStage('Flat Room'); // no hierarchy
    await expect(venue.reportTo('Done')).rejects.toThrow('No supervisor');
  });
});

describe('Maestro SDK — Blackboard', () => {
  it('sets and gets via StageHandle', async () => {
    const m = makeMaestro('Alpha');
    const venue = m.createOpenStage('Room');

    await venue.blackboard.set('status', { phase: 'design' }, 'Alpha');
    expect(await venue.blackboard.get('status')).toEqual({ phase: 'design' });
  });

  it('different stages have isolated blackboards', async () => {
    const m = makeMaestro('Alpha');
    const v1 = m.createOpenStage('Room 1');
    const v2 = m.createOpenStage('Room 2');

    await v1.blackboard.set('key', 'room1-value', 'Alpha');
    expect(await v2.blackboard.get('key')).toBeUndefined();
  });

  it('subscribeAll fires on any write', async () => {
    const m = makeMaestro('Alpha');
    const venue = m.createOpenStage('Room');

    const keys: string[] = [];
    venue.blackboard.subscribeAll((entry) => keys.push(entry.key));

    await venue.blackboard.set('a', 1, 'Alpha');
    await venue.blackboard.set('b', 2, 'Alpha');

    expect(keys).toContain('a');
    expect(keys).toContain('b');
  });
});

describe('Maestro SDK — Venue lifecycle', () => {
  it('closes a Stage', async () => {
    const m = makeMaestro('Alpha');
    const venue = m.createOpenStage('Room');
    const venueId = venue.stageId;

    await venue.close();

    expect(m.getStage(venueId)).toBeUndefined();
    expect(m.stageManager.get(venueId)?.status).toBe('closed');
  });

  it('guest can leave Stage', async () => {
    const host = makeMaestro('Alpha');
    const guest = makeMaestro('Beta');
    const hostVenue = host.createOpenStage('Room');
    guest.join(hostVenue.stageId, host.stageManager);

    const guestVenue = guest.getStage(hostVenue.stageId)!;
    await guestVenue.leave();

    expect(guest.getStage(hostVenue.stageId)).toBeUndefined();
    expect(host.stageManager.getMember(hostVenue.stageId, 'Beta')).toBeUndefined();
  });

  it('lists all stages', () => {
    const m = makeMaestro('Alpha');
    m.createOpenStage('Room 1');
    m.createOpenStage('Room 2');
    expect(m.listStages()).toHaveLength(2);
  });
});

describe('Maestro SDK — provenance policy enforcement', () => {
  it('rejects message missing required provenance', async () => {
    const m = makeMaestro('Alpha');
    const venue = m.createStage({
      name: 'Secure Stage',
      rules: {
        entryMode: 'open',
        memberVisibility: 'all',
        permissions: { lead: ['message:send', 'message:broadcast', 'blackboard:read', 'blackboard:write', 'member:invite', 'member:remove', 'role:assign', 'stage:close', 'stage:transfer'], worker: ['message:send', 'blackboard:read', 'blackboard:write'] },
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
      stageId: venue.stageId,
      version: '3.2',
    };

    const result = await m.receive(msg);
    expect(result.accepted).toBe(false);
    expect(result.reason).toContain('provenance_required');
  });

  it('accepts message with provenance when required', async () => {
    const m = makeMaestro('Alpha');
    const venue = m.createStage({
      name: 'Secure Stage',
      rules: {
        entryMode: 'open',
        memberVisibility: 'all',
        permissions: { lead: ['message:send', 'message:broadcast', 'blackboard:read', 'blackboard:write', 'member:invite', 'member:remove', 'role:assign', 'stage:close', 'stage:transfer'], worker: ['message:send', 'blackboard:read', 'blackboard:write'] },
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
      stageId: venue.stageId,
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

