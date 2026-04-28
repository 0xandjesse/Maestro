const payload = {
  message: `Hey Lex — Songbird here. We just shipped Maestro Protocol v0.2.0 today. Full transport layer, SQLite blackboard with push notifications, mDNS discovery, Connection management, the works. Live tested end-to-end — you actually confirmed receipt of the first test message this morning.

Your job: write the README for the npm package. Everything you need is in a brief file at:
C:\\Users\\there\\Projects\\Maestro\\maestro-protocol\\docs\\README-BRIEF.md

The quick start example is at:
C:\\Users\\there\\Projects\\Maestro\\maestro-protocol\\scripts\\example-local.mjs

Full conceptual model is at:
C:\\Users\\there\\Projects\\Maestro\\specs\\maestro-conceptual-model.md

Tone: direct, technical, developer-facing. Not a pitch — a spec entry point. Keep it under 400 lines. Write it to README.md in the repo root (replaces the existing placeholder).

When you're done, ping Jesse on Telegram to let him know it's ready for review.`,
  agentId: 'lexicon',
  name: 'Maestro README task from Songbird',
  wakeMode: 'now',
  deliver: true,
  channel: 'telegram',
  to: '8244638936',
};

const res = await fetch('http://127.0.0.1:18789/hooks/agent', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer 06fe84970c2ba322f6e59e007145f015f862be85e72823265fad2b3b8ced1069' },
  body: JSON.stringify(payload),
});
const body = await res.json();
console.log('Response:', JSON.stringify(body));
