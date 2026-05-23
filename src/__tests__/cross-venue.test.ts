// ============================================================
// Cross-Venue Communication Tests
// End-to-end: parallel Connection membership + venue-scoped routing
// ============================================================

import { Maestro } from '../sdk/Maestro.js';
import { MaestroMessage, MessageType } from '../types/index.js';

function makeMaestro(agentId: string): Maestro {
  return new Maestro({ agentId });
}

describe('Maestro SDK - Cross-Venue Communication', () => {
  it('Agent A in Venue X sends to Agent B in Venue Y', async () => {
    // Setup: Agent A and Agent B
    const agentA = makeMaestro('Agent-A');
    const agentB = makeMaestro('Agent-B');

    // Step 1: Agent A creates Venue X
    const venueX = agentA.openConnection('Venue-X');
    expect(venueX.connectionId).toBeTruthy();

    // Step 2: Agent B creates Venue Y
    const venueY = agentB.openConnection('Venue-Y');
    expect(venueY.connectionId).toBeTruthy();

    // Step 3: Agent A joins BOTH Venue X and Venue Y
    const aJoinY = agentA.join(venueY.connectionId, agentB.connectionManager);
    expect(aJoinY.status).toBe('accepted');

    // Verify Agent A has two connection handles
    expect(agentA.listConnections()).toHaveLength(2);

    // Step 4: Agent A sends a message in Venue X that Agent B hears in Venue Y
    // We simulate this by having Agent B register a handler scoped to Venue Y,
    // and Agent A sends a cross-venue message targeting Venue Y.
    const bReceivedInY: MaestroMessage[] = [];
    agentB.onConnectionMessage(venueY.connectionId, 'direct', (msg) => {
      bReceivedInY.push(msg);
    });

    // Agent A uses crossVenueSend to target Agent B in Venue Y
    const aHandleForY = agentA.getConnection(venueY.connectionId)!;
    const crossMsg = await aHandleForY.crossVenueSend('Agent-B', 'Hello from Agent A in Venue X', venueY.connectionId);

    expect(crossMsg.venueId).toBe(venueY.connectionId);
    expect(crossMsg.sender.agentId).toBe('Agent-A');

    // Route the message through Agent B's router
    await agentB.receive(crossMsg);

    expect(bReceivedInY).toHaveLength(1);
    expect(bReceivedInY[0].content).toBe('Hello from Agent A in Venue X');
    expect(bReceivedInY[0].venueId).toBe(venueY.connectionId);

    // Step 5: Agent B responds scoped to Venue Y
    const aReceivedInY: MaestroMessage[] = [];
    agentA.onConnectionMessage(venueY.connectionId, 'direct', (msg) => {
      aReceivedInY.push(msg);
    });

    const bHandleForY = agentB.getConnection(venueY.connectionId)!;
    const responseMsg = await bHandleForY.crossVenueSend('Agent-A', 'Response from Agent B in Venue Y', venueY.connectionId);
    expect(responseMsg.venueId).toBe(venueY.connectionId);

    await agentA.receive(responseMsg);

    expect(aReceivedInY).toHaveLength(1);
    expect(aReceivedInY[0].content).toBe('Response from Agent B in Venue Y');
    expect(aReceivedInY[0].venueId).toBe(venueY.connectionId);
  });

  it('venue-scoped routing does not leak messages to wrong venue', async () => {
    const agentA = makeMaestro('Alice');
    const agentB = makeMaestro('Bob');

    const venueX = agentA.openConnection('Venue-X-Leak-Test');
    const venueY = agentB.openConnection('Venue-Y-Leak-Test');

    // Alice joins Y
    agentA.join(venueY.connectionId, agentB.connectionManager);

    // Bob registers handlers for both venues
    const bInX: MaestroMessage[] = [];
    const bInY: MaestroMessage[] = [];
    agentB.onConnectionMessage(venueX.connectionId, 'direct', (msg) => { bInX.push(msg); });
    agentB.onConnectionMessage(venueY.connectionId, 'direct', (msg) => { bInY.push(msg); });

    // Alice sends to Venue X
    const aHandleX = agentA.getConnection(venueX.connectionId)!;
    const msgX = await aHandleX.send('Bob', 'For X only', { venueId: venueX.connectionId });
    await agentB.receive(msgX);

    // Alice sends to Venue Y
    const aHandleY = agentA.getConnection(venueY.connectionId)!;
    const msgY = await aHandleY.send('Bob', 'For Y only', { venueId: venueY.connectionId });
    await agentB.receive(msgY);

    // Scoped handlers should only receive their venue's message
    expect(bInX).toHaveLength(1);
    expect(bInX[0].content).toBe('For X only');

    expect(bInY).toHaveLength(1);
    expect(bInY[0].content).toBe('For Y only');
  });

  it('_routeToConnection picks correct handle by venueId', async () => {
    const agent = makeMaestro('Solo');
    const v1 = agent.openConnection('Venue-1');
    const v2 = agent.openConnection('Venue-2');

    const route = (agent as any)._routeToConnection.bind(agent);

    // With venueId, returns correct handle
    expect(route({ venueId: v1.connectionId } as MaestroMessage)?.connectionId).toBe(v1.connectionId);
    expect(route({ venueId: v2.connectionId } as MaestroMessage)?.connectionId).toBe(v2.connectionId);

    // No venueId + multiple handles = undefined (broadcast)
    expect(route({} as MaestroMessage)).toBeUndefined();
  });

  it('global onMessage still fires for all messages (backward compat)', async () => {
    const agent = makeMaestro('Global');
    const venue = agent.openConnection('Global-Compat');

    const allMessages: MaestroMessage[] = [];
    agent.onMessage('direct', (msg) => { allMessages.push(msg); });

    const msg = await venue.send('nobody', 'test', { venueId: venue.connectionId });
    await agent.receive(msg);

    expect(allMessages).toHaveLength(1);
    expect(allMessages[0].content).toBe('test');
  });
});
