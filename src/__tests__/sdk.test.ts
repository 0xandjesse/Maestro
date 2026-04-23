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

describe('Maestro SDK — Venue creation', () => {
  it('creates an open Venue', () => {
    const m = makeMaestro('Alpha');
    const venue = m.createOpenVenue('Test Room');
    expect(venue.venueId).toBeTruthy();
    expect(venue.getVenueInfo().name).toBe('Test Room');
    expect(venue.getVenueInfo().hostId).toBe('Alpha');
  });

  it('creates a hierarchical Venue', () => {
    const m = makeMaestro('Alpha');
    const venue = m.createHierarchicalVenue(
      'Task Venue',
      ['lead', 'worker'],
      { worker: 'lead' },
    );
    const info = venue.getVenueInfo();
    expect(info.rules.hierarchy?.roles).toContain('lead');
    expect(info.rules.hierarchy?.roles).toContain('worker');
  });

  it('host is a member with lead role', () => {
    const m = makeMaestro('Alpha');
    const venue = m.createOpenVenue('Room');
    const member = venue.getMember('Alpha');
    expect(member?.role).toBe('lead');
  });
});

describe('Maestro SDK — joining Venues', () => {
  it('joins an open Venue', () => {
    const host = makeMaestro('Alpha');
    const guest = makeMaestro('Beta');

    const venue = host.createOpenVenue('Open Room');
    const response = guest.join(venue.venueId, host.venueManager);

    expect(response.status).toBe('accepted');
    expect(response.role).toBe('worker');
  });

  it('gets a VenueHandle after joining', () => {
    const host = makeMaestro('Alpha');
    const guest = makeMaestro('Beta');

    const hostVenue = host.createOpenVenue('Room');
    guest.join(hostVenue.venueId, host.venueManager);

    const guestVenue = guest.getVenue(hostVenue.venueId);
    expect(guestVenue).toBeDefined();
    expect(guestVenue?.venueId).toBe(hostVenue.venueId);
  });

  it('rejects join to unknown venue', () => {
    const m = makeMaestro('Alpha');
    const response = m.join('nonexistent-venue-id', m.venueManager);
    expect(response.status).toBe('rejected');
  });
});

describe('Maestro SDK — messaging', () => {
  it('builds a direct message', async () => {
    const host = makeMaestro('Alpha');
    const venue = host.createOpenVenue('Room');

    const msg = await venue.send('Beta', 'Hello Beta');
    expect(msg.type).toBe('direct');
    expect(msg.content).toBe('Hello Beta');
    expect(msg.sender.agentId).toBe('Alpha');
    expect(msg.recipient).toBe('Beta');
    expect(msg.venueId).toBe(venue.venueId);
  });

  it('builds a broadcast message', async () => {
    const host = makeMaestro('Alpha');
    const venue = host.createOpenVenue('Room');

    const msg = await venue.broadcast('Hello everyone');
    expect(msg.type).toBe('broadcast');
    expect(msg.recipient).toBe('*');
  });

  it('dispatches inbound message to handler', async () => {
    const host = makeMaestro('Alpha');
    const guest = makeMaestro('Beta');
    const hostVenue = host.createOpenVenue('Room');
    guest.join(hostVenue.venueId, host.venueManager);

    const received: MaestroMessage[] = [];
    host.onMessage('direct' as MessageType, (msg) => { received.push(msg); });

    const msg = await guest.getVenue(hostVenue.venueId)!.send('Alpha', 'Hey Alpha');
    await host.receive(msg);

    expect(received).toHaveLength(1);
    expect(received[0].content).toBe('Hey Alpha');
  });

  it('dispatches to wildcard handler', async () => {
    const host = makeMaestro('Alpha');
    const venue = host.createOpenVenue('Room');

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
    const venue = lead.createVenue({
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

    worker.join(venue.venueId, lead.venueManager);

    const yumavenue = worker.getVenue(venue.venueId)!;
    const msg = await yumavenue.reportTo('Frontend complete');

    expect(msg.type).toBe('report');
    expect(msg.recipient).toBe('Lex');
  });

  it('assignTo sends to subordinate', async () => {
    const lead = makeMaestro('Lex');
    const worker = makeMaestro('Yuma');

    const venue = lead.createVenue({
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
    worker.join(venue.venueId, lead.venueManager);

    const lexVenue = lead.getVenue(venue.venueId)!;
    const msg = await lexVenue.assignTo('Yuma', 'Build the frontend');

    expect(msg.type).toBe('assign');
    expect(msg.recipient).toBe('Yuma');
  });

  it('reportTo throws without supervisor', async () => {
    const lead = makeMaestro('Lex');
    const venue = lead.createOpenVenue('Flat Room'); // no hierarchy
    await expect(venue.reportTo('Done')).rejects.toThrow('No supervisor');
  });
});

describe('Maestro SDK — Blackboard', () => {
  it('sets and gets via VenueHandle', async () => {
    const m = makeMaestro('Alpha');
    const venue = m.createOpenVenue('Room');

    await venue.blackboard.set('status', { phase: 'design' }, 'Alpha');
    expect(await venue.blackboard.get('status')).toEqual({ phase: 'design' });
  });

  it('different venues have isolated blackboards', async () => {
    const m = makeMaestro('Alpha');
    const v1 = m.createOpenVenue('Room 1');
    const v2 = m.createOpenVenue('Room 2');

    await v1.blackboard.set('key', 'room1-value', 'Alpha');
    expect(await v2.blackboard.get('key')).toBeUndefined();
  });

  it('subscribeAll fires on any write', async () => {
    const m = makeMaestro('Alpha');
    const venue = m.createOpenVenue('Room');

    const keys: string[] = [];
    venue.blackboard.subscribeAll((entry) => keys.push(entry.key));

    await venue.blackboard.set('a', 1, 'Alpha');
    await venue.blackboard.set('b', 2, 'Alpha');

    expect(keys).toContain('a');
    expect(keys).toContain('b');
  });
});

describe('Maestro SDK — Venue lifecycle', () => {
  it('closes a Venue', async () => {
    const m = makeMaestro('Alpha');
    const venue = m.createOpenVenue('Room');
    const venueId = venue.venueId;

    await venue.close();

    expect(m.getVenue(venueId)).toBeUndefined();
    expect(m.venueManager.get(venueId)?.status).toBe('closed');
  });

  it('guest can leave Venue', async () => {
    const host = makeMaestro('Alpha');
    const guest = makeMaestro('Beta');
    const hostVenue = host.createOpenVenue('Room');
    guest.join(hostVenue.venueId, host.venueManager);

    const guestVenue = guest.getVenue(hostVenue.venueId)!;
    await guestVenue.leave();

    expect(guest.getVenue(hostVenue.venueId)).toBeUndefined();
    expect(host.venueManager.getMember(hostVenue.venueId, 'Beta')).toBeUndefined();
  });

  it('lists all venues', () => {
    const m = makeMaestro('Alpha');
    m.createOpenVenue('Room 1');
    m.createOpenVenue('Room 2');
    expect(m.listVenues()).toHaveLength(2);
  });
});

describe('Maestro SDK — provenance policy enforcement', () => {
  it('rejects message missing required provenance', async () => {
    const m = makeMaestro('Alpha');
    const venue = m.createVenue({
      name: 'Secure Venue',
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
      venueId: venue.venueId,
      version: '3.2',
    };

    const result = await m.receive(msg);
    expect(result.accepted).toBe(false);
    expect(result.reason).toContain('provenance_required');
  });

  it('accepts message with provenance when required', async () => {
    const m = makeMaestro('Alpha');
    const venue = m.createVenue({
      name: 'Secure Venue',
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
      venueId: venue.venueId,
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
