// Quick local loopback test — two Maestro instances, one sends, one receives
import { Maestro } from '../dist/index.js';

const REGISTRY = '.maestro/test-registry.json';

const receiver = new Maestro({
  agentId: 'lex',
  transport: { port: 3843, registryPath: REGISTRY },
  discovery: { method: 'mdns' },
});

const sender = new Maestro({
  agentId: 'songbird',
  transport: { port: 3844, registryPath: REGISTRY },
  discovery: { method: 'mdns' },
});

await receiver.start();
await sender.start();

receiver.onMessage('direct', (msg) => {
  console.log(`[LEX RECEIVED] from ${msg.sender.agentId}: ${msg.content}`);
  console.log('✅ Smoke test PASSED');
  process.exit(0);
});

// Give registry time to write (1000ms — mDNS needs a moment to discover peers,
// and both agents write to the same file registry as a reliable fallback)
await new Promise(r => setTimeout(r, 1000));

// Songbird sends directly to lex
const result = await sender.sendDirect('lex', 'Hello Lex, transport is working!');
if (!result.ok) {
  console.error('SEND FAILED:', result.error);
  await Promise.all([receiver.stop(), sender.stop()]);
  process.exit(1);
}

console.log('[SONGBIRD] Message sent OK');

// Timeout if not received in 3s
setTimeout(async () => {
  console.error('TIMEOUT — message not received');
  await Promise.all([receiver.stop(), sender.stop()]).catch(() => {});
  process.exit(1);
}, 3000);
