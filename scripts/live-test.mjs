// ============================================================
// Maestro Live Integration Test
// ============================================================
// Boots a real transport for "songbird" and sends a direct
// message to "lexicon". If the OpenClaw hook is wired correctly,
// Lex will wake up in Telegram and receive the message.
//
// Usage: node scripts/live-test.mjs
// ============================================================

import { Maestro } from '../dist/index.js';
import { readFileSync } from 'fs';

const config = JSON.parse(readFileSync('./maestro.config.json', 'utf8'));
const songbirdCfg = config.agents.find(a => a.agentId === 'songbird');

console.log('[live-test] Starting Songbird transport...');

const songbird = new Maestro({
  agentId: 'songbird',
  transport: songbirdCfg.transport,
  openclaw: songbirdCfg.openclaw,
});

await songbird.start();
console.log('[live-test] Transport up on port', songbirdCfg.transport.port);

// Give registry time to settle
await new Promise(r => setTimeout(r, 300));

// Check health
try {
  const res = await fetch(`http://127.0.0.1:${songbirdCfg.transport.port}/health`);
  const health = await res.json();
  console.log('[live-test] Health:', health);
} catch (e) {
  console.error('[live-test] Health check failed:', e.message);
}

console.log('\n[live-test] Sending message to lexicon...');
console.log('[live-test] Note: Lex is not running her own transport yet,');
console.log('[live-test] so this will test the OpenClaw hook path directly.\n');

// Since Lex's transport isn't running, we'll test the hook directly
// by calling the OpenClawAdapter manually via a direct POST to /hooks/agent
const hookUrl = 'http://127.0.0.1:18789/hooks/agent';
const hookToken = songbirdCfg.openclaw.hookToken;

const payload = {
  message: '[Maestro] direct from songbird: Hey Lex — Maestro transport is live. This message was delivered via the OpenClaw hook. If you can read this, the integration is working. 🎉',
  agentId: 'lexicon',
  name: 'Maestro from songbird',
  wakeMode: 'now',
};

try {
  const res = await fetch(hookUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${hookToken}`,
    },
    body: JSON.stringify(payload),
  });

  const body = await res.text();
  console.log(`[live-test] Hook response: HTTP ${res.status}`);
  console.log('[live-test] Body:', body);

  if (res.ok) {
    console.log('\n✅ Hook accepted! Check Lex in Telegram — she should be responding shortly.');
  } else {
    console.log('\n❌ Hook rejected. Check the response above for details.');
  }
} catch (e) {
  console.error('[live-test] Hook call failed:', e.message);
}

await songbird.stop();
console.log('\n[live-test] Transport stopped. Done.');
