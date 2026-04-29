import { randomUUID } from 'crypto';

const msg = {
  id: randomUUID(),
  type: 'direct',
  content: 'Debug roundtrip — Songbird to Hermes via transport. Please confirm.',
  sender: { agentId: 'songbird' },
  recipient: 'hermes',
  timestamp: Date.now(),
  version: '3.2',
};

console.log('Sending to hermes transport:', msg.id);
const r = await fetch('http://127.0.0.1:3844/message', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(msg),
});
console.log('Status:', r.status, await r.text());
console.log('Waiting 90s for reply in transport log...');

// Watch log for reply
import { readFileSync } from 'fs';
const logPath = 'C:/Users/there/Projects/Maestro/maestro-protocol/.maestro/transport-service.log';
const deadline = Date.now() + 90000;
let lastSize = readFileSync(logPath, 'utf8').length;

while (Date.now() < deadline) {
  await new Promise(r => setTimeout(r, 1000));
  const log = readFileSync(logPath, 'utf8');
  if (log.length > lastSize) {
    const newContent = log.slice(lastSize);
    lastSize = log.length;
    for (const line of newContent.split('\n')) {
      if (line.trim()) console.log('LOG:', line);
    }
  }
}
console.log('Done watching.');
