// Test Hermes integration via SSE events stream
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const config = JSON.parse(readFileSync(resolve(__dirname, '..', 'maestro.config.json'), 'utf8'));
const { apiUrl, apiKey } = config.hermesAgents[0];

console.log(`[test] Target: ${apiUrl}`);

// Create run
const runRes = await fetch(`${apiUrl}/v1/runs`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
  body: JSON.stringify({
    input: 'Hey — this is a Maestro integration test from Songbird on the Windows host. Reply with just your name and a one-sentence confirmation.',
    conversation: 'maestro-test',
  }),
});

const run = await runRes.json();
console.log(`[test] Run created: ${run.run_id} (${run.status})`);

if (!run.run_id) { console.error('No run_id'); process.exit(1); }

// Subscribe to SSE events
console.log(`[test] Subscribing to events...`);
const eventsRes = await fetch(`${apiUrl}/v1/runs/${run.run_id}/events`, {
  headers: { Authorization: `Bearer ${apiKey}`, Accept: 'text/event-stream' },
  signal: AbortSignal.timeout(120000),
});

console.log(`[test] Events stream status: ${eventsRes.status}`);

const reader = eventsRes.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  const chunk = decoder.decode(value, { stream: true });
  for (const line of chunk.split('\n')) {
    if (line.trim()) console.log(`[event] ${line}`);
  }
}

console.log('[test] Stream ended.');
