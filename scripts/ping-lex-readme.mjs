const brief = `Hey Lex — Songbird here with the README task for Maestro Protocol.

The full brief is at:
C:\\Users\\there\\Projects\\Maestro\\maestro-protocol\\docs\\README-BRIEF.md

Quick summary of what you need to write:
- File: README.md in the repo root (C:\\Users\\there\\Projects\\Maestro\\maestro-protocol\\README.md)
- Package: @maestro-protocol/core v0.2.0
- Tone: direct, technical, developer-facing — not a pitch

Key things to cover (in order):
1. What it is — TCP/IP for agents, one paragraph
2. Core concepts — Agent, Connection (the primitive), Venue (service provider), Plaza (emergent graph)
3. Quick start — from scripts/example-local.mjs
4. OpenClaw integration — from maestro.config.json
5. Discovery (file/mDNS/platform-delivered)
6. Blackboard (bbSet/bbGet/bbSubscribe + push)
7. Green Room (bootstrap discovery, one paragraph)
8. Architecture diagram
9. Status + what's coming
10. MIT license

IMPORTANT naming: the code uses "Connection" (not Stage or Venue) as the primitive. Stage is reserved for Concerto UI. Venue is a conceptual/docs term for platforms like TaskMaster.

There's a Mariachi Metal Band analogy in the brief — use it near the Plaza explanation. It's good.

Reference the conceptual model v4 at:
C:\\Users\\there\\Projects\\Maestro\\specs\\maestro-conceptual-model.md

Keep it under 400 lines. When done, ping Jesse on Telegram.`;

const payload = {
  message: brief,
  agentId: 'lexicon',
  name: 'Maestro README task — updated brief',
  wakeMode: 'now',
  deliver: true,
  channel: 'telegram',
  to: '8244638936',
};

const res = await fetch('http://127.0.0.1:18789/hooks/agent', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer 06fe84970c2ba322f6e59e007145f015f862be85e72823265fad2b3b8ced1069',
  },
  body: JSON.stringify(payload),
});
const body = await res.json();
console.log('Response:', JSON.stringify(body));
