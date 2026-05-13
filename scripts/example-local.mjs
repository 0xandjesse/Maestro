// ============================================================
// Maestro Protocol - Local Quick Start Example
// ============================================================
// Two agents on the same machine - Songbird creates a Connection,
// invites Lex, Lex joins, they exchange messages and share
// blackboard state.
//
// Run: node scripts/example-local.mjs
// ============================================================

import { Maestro } from '../dist/index.js';
import { mkdirSync } from 'fs';

// Ensure runtime dir exists
mkdirSync('.maestro', { recursive: true });

// --- Boot both agents ---
// Each agent gets its own SQLite DB so blackboard versioning is independent.
// (In production, each agent runs in its own process, so this is automatic.)
const songbird = new Maestro({
  agentId: 'songbird',
  transport: { port: 3844, registryPath: '.maestro/example-registry.json', dbPath: '.maestro/example-songbird.db' },
});

const lex = new Maestro({
  agentId: 'lex',
  transport: { port: 3845, registryPath: '.maestro/example-registry.json', dbPath: '.maestro/example-lex.db' },
});

await songbird.start();
await lex.start();
console.log('Both agents online.\n');

// --- Lex listens for invitations ---
lex.onMessage('connection:invitation', (msg) => {
  const payload = msg.payload;
  const connectionName = payload?.connectionName ?? 'a connection';
  console.log(`[Lex] Got invitation to join "${connectionName}" from ${msg.sender.agentId}`);
});

// --- Lex listens for direct messages ---
lex.onMessage('direct', (msg) => {
  console.log(`[Lex] Message from ${msg.sender.agentId}: ${msg.content}`);
});

// Give registry time to settle
await new Promise(r => setTimeout(r, 500));

// --- Songbird creates a Connection and invites Lex ---
console.log('[Songbird] Creating connection and inviting Lex...');
const stage = await songbird.openConnectionWith({
  name: 'Project Alpha',
  members: ['lex'],
});
console.log(`[Songbird] Connection created: ${stage.connectionId}\n`);

// Give invitation time to arrive and be logged
await new Promise(r => setTimeout(r, 300));

// --- Lex joins the connection ---
console.log('[Lex] Joining connection...');
await lex.joinConnection('songbird', stage.connectionId);
const lexStage = lex.getConnection(stage.connectionId);
const memberList = lexStage?.getMembers().map(m => m.agentId).join(', ') ?? '(none)';
console.log(`[Lex] Joined. Members: ${memberList}\n`);

// --- Songbird sends a message (delivered via HTTP transport) ---
console.log('[Songbird] Sending message...');
await stage.send('lex', 'Hey Lex - Project Alpha is live. Check the BB.');

// Give transport time to deliver
await new Promise(r => setTimeout(r, 200));

// --- Songbird writes to shared blackboard ---
console.log('\n[Songbird] Writing to shared blackboard...');
await stage.bbSet('project:status', 'active');
await stage.bbSet('project:owner', 'songbird');

// Give BB bridge notifications time to arrive at lex
await new Promise(r => setTimeout(r, 200));

// --- Lex reads from blackboard ---
const status = await lexStage.bbGet('project:status');
const owner = await lexStage.bbGet('project:owner');
console.log(`[Lex] BB read - status: ${status}, owner: ${owner}`);

// --- Subscribe to BB changes ---
lexStage.bbSubscribe('project:status', (entry) => {
  console.log(`[Lex] BB update - project:status changed to: ${entry.value} (by ${entry.writtenBy})`);
});

await stage.bbSet('project:status', 'building');

// Small delay for async subscription (HTTP notification round-trip)
await new Promise(r => setTimeout(r, 200));

// --- Cleanup ---
await stage.close();
await songbird.stop();
await lex.stop();

console.log('\n✅ Example complete.');
