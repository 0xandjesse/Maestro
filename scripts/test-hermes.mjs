// ============================================================
// Maestro Protocol — Hermes Integration Test
// ============================================================
// Tests the full path: Maestro transport → HermesAdapter → Hermes API
//
// Usage:
//   node scripts/test-hermes.mjs
//   node scripts/test-hermes.mjs --await   (wait for response)
// ============================================================

import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, '..');

const awaitResponse = process.argv.includes('--await');

// Load config
const configPath = resolve(repoRoot, 'maestro.config.json');
const config = JSON.parse(readFileSync(configPath, 'utf8'));
const hermesAgents = config.hermesAgents ?? [];

if (hermesAgents.length === 0) {
  console.error('[test-hermes] No hermesAgents configured in maestro.config.json');
  process.exit(1);
}

const hermesCfg = hermesAgents[0];
const { apiUrl, apiKey } = hermesCfg;

console.log(`[test-hermes] Target: ${apiUrl}`);
console.log(`[test-hermes] Agent: ${hermesCfg.agentId}`);
console.log(`[test-hermes] Await response: ${awaitResponse}`);
console.log('');

// 1. Health check
console.log('[test-hermes] Step 1: Health check...');
try {
  const health = await fetch(`${apiUrl}/health`, { signal: AbortSignal.timeout(5000) });
  if (health.ok) {
    const body = await health.json();
    console.log('[test-hermes] ✓ Hermes API reachable:', JSON.stringify(body));
  } else {
    console.error(`[test-hermes] ✗ Health check failed: ${health.status}`);
    process.exit(1);
  }
} catch (err) {
  console.error(`[test-hermes] ✗ Health check error: ${err.message}`);
  console.error('[test-hermes] Is the VirtualBox port forwarding set up? Is Hermes gateway running?');
  process.exit(1);
}

// 2. Send a test message via /v1/runs
console.log('\n[test-hermes] Step 2: Sending test message via /v1/runs...');
const prompt = `[Maestro Protocol — Integration Test]
From: songbird
Type: direct

Hey — this is Songbird on the Windows host. Maestro transport integration test. 
If you're reading this, the Hermes adapter is working.
Reply with a short confirmation and your agent name.`;

const body = {
  input: prompt,
  conversation: hermesCfg.agentSessions?.hermes ?? 'maestro-test',
};

try {
  const runRes = await fetch(`${apiUrl}/v1/runs`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(10000),
  });

  if (!runRes.ok) {
    const text = await runRes.text().catch(() => '');
    console.error(`[test-hermes] ✗ Run creation failed: ${runRes.status} — ${text}`);
    process.exit(1);
  }

  const runData = await runRes.json();
  console.log(`[test-hermes] ✓ Run created: ${JSON.stringify(runData)}`);

  if (!awaitResponse) {
    console.log('\n[test-hermes] Done (fire-and-forget). Run: node scripts/test-hermes.mjs --await to wait for response.');
    process.exit(0);
  }

  // 3. Poll for completion
  const runId = runData.run_id;
  if (!runId) {
    console.error('[test-hermes] ✗ No run_id returned');
    process.exit(1);
  }

  console.log(`\n[test-hermes] Step 3: Polling run ${runId} for completion...`);
  const deadline = Date.now() + 90000;

  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 1000));

    const pollRes = await fetch(`${apiUrl}/v1/runs/${runId}`, {
      headers: { Authorization: `Bearer ${apiKey}` },
      signal: AbortSignal.timeout(5000),
    });

    if (!pollRes.ok) continue;
    const pollData = await pollRes.json();
    const status = pollData.status;

    process.stdout.write(`  status: ${status}\r`);

    if (status === 'completed') {
      console.log(`\n[test-hermes] ✓ Run completed!`);
      console.log(`[test-hermes] Response:\n\n${pollData.output}\n`);
      process.exit(0);
    }
    if (status === 'failed' || status === 'cancelled') {
      console.error(`\n[test-hermes] ✗ Run ${status}`);
      process.exit(1);
    }
  }

  console.error('\n[test-hermes] ✗ Timed out waiting for run completion');
  process.exit(1);

} catch (err) {
  console.error(`[test-hermes] ✗ Error: ${err.message}`);
  process.exit(1);
}
