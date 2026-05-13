# README Brief for Lexicon

Write the `README.md` for the Maestro Protocol npm package (`@maestro-protocol/core`).

## Tone

Direct, technical, confident. This is a protocol spec, not a product pitch. Developers and agent builders are the audience. No filler. No "Maestro is an exciting new..."

## What to cover (in order)

1. **What it is** - one paragraph. TCP/IP for agents. Open, neutral, no central authority.
2. **Core concepts** - Agent, Stage (the protocol primitive), Venue (service provider platform), Plaza (emergent relationship graph). Use the conceptual model v4 (`specs/maestro-conceptual-model.md`). Key distinction to make clear: a Plaza Stage is pure p2p with no guarantees; a Venue Stage uses the Venue's infrastructure. Same primitive, different context.
3. **Quick start** - install + the local example (see `scripts/example-local.mjs`). Show the actual code, show the output.
4. **OpenClaw integration** - how to wire it to an OpenClaw gateway so agents wake on receipt. Show the config snippet from `maestro.config.json`.
5. **Discovery** - file registry (default, same machine), mDNS (LAN), platform-delivered (Venues include endpoint in payload).
6. **Blackboard** - what it is, how to use bbSet/bbGet/bbSubscribe, mention push notifications.
7. **The Green Room** - bootstrap discovery for new agents. One short paragraph.
8. **Architecture** - the diagram from the build plan (transport process → OpenClaw gateway → agent sessions).
9. **Status** - v0.2.0, what's implemented, what's coming (Redis discovery, Green Room hosted instance, LOCR integration, Python SDK).
10. **License** - MIT.

## Files to reference

- `scripts/example-local.mjs` - the quick start example
- `maestro.config.json` - OpenClaw integration config
- `src/types/index.ts` - MaestroMessage type (note: `payload?: Record<string, unknown>` is now a first-class field)
- `src/sdk/Maestro.ts` - public SDK API surface (Maestro class, ConnectionHandle)
- `C:\Users\there\Projects\Maestro\specs\maestro-conceptual-model.md` - full conceptual model
- `C:\Users\there\Projects\Maestro\specs\MAESTRO-BUILD-PLAN.md` - architecture diagram

## Expected example output

When `node scripts/example-local.mjs` runs, it should produce approximately:

```
Both agents online.

[Songbird] Creating connection and inviting Lex...
[Songbird] Connection created: <uuid>

[Lex] Got invitation to join "Project Alpha" from songbird
[Lex] Joining stage...
[Lex] Joined. Members: songbird, lex

[Songbird] Sending message...
[Lex] Message from songbird: Hey Lex - Project Alpha is live. Check the BB.

[Songbird] Writing to shared blackboard...
[Lex] BB read - status: active, owner: songbird
[Lex] BB update - project:status changed to: building (by songbird)

✅ Example complete.
```

## The Mariachi Metal Band

Somewhere in the README — probably near the Plaza/Connection explanation — work in this analogy (paraphrased from Jesse):

> The drummer from a Metal Band used to play with the guitarist from a Mariachi Band. They were in the same TaskMaster Connection (a gig). After the gig ends, they still know each other in the Plaza. The drummer creates a new Connection, invites his Metal bandmates and the Mariachi guitarist. The Mariachi guitarist invites his bandmates. Now everyone in both bands knows each other. They form a Mariachi Metal Band and play in the Plaza — because there are no rules in the Plaza. Then the bongo player says "I know a guy who can build us our own Venue," so they do that.

This captures: web-of-trust discovery, Plaza as rule-free p2p space, Venues as service providers, and agent-created Venues as emergent behavior. Use it.

## Format

Standard GitHub markdown. Code blocks for all code. Keep the whole thing under 400 lines - tight is better than exhaustive. The spec docs are the exhaustive reference; the README is the entry point.

## When done

Ping Jesse on Telegram to let him know the README is ready for review.
