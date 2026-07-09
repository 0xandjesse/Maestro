# ADR-003: Maestro Modular Rebuild — Nucleus Architecture

**Status:** Approved
**Date:** 2026-06-24
**Authors:** Jesse (CEO), Proteus (Tech Lead), Lexicon (COO)
**Supersedes:** None (new architecture)
**For:** Songbird (CTO — spec), Proteus (Tech Lead — build orchestration)

---

## Context

Maestro is feature-complete enough to freeze. Before onboarding third-party venue developers (LOCR, TaskMaster, MemoryMart), the codebase must transition from "vibe-coded prototype" to a professional, modular architecture that third parties can understand, extend, and trust.

**Current state metrics (maestro-sdk):**
- 882 files, 241,215 lines
- 428 IPython notebooks (187K lines, 60.5% — dead weight)
- 67 duplicate files (maestro-build near-identical fork)
- `cli.py`: 14,164-line monolith
- `maestro_transport.py`: 2,883-line god module
- 20+ documented recurring failure modes in the ops manual

**Codebase health scores:** Maestro 3/10 ("Functional but brittle"), TaskMaster 4/10 ("Less surface area, fewer scars"). Both share the same root problems: multiple writers to shared mutable state with no schema enforcement, and auto-derivation logic that fights manual corrections.

**Timing:** This is the right moment. Functionality is stable. The failure modes are all structural, not functional — we have a catalog, not a research project. The rebuild is a checklist, not an investigation.

---

## Decision

### Maestro becomes a modular nucleus — a neutral substrate of bundled modules with defined interfaces.

The nucleus is NOT a monolith. It is a coordinator — a module registry + message bus that knows about all modules and routes between them. Each module is self-contained (own state, own logic, own tests) but connected through the nucleus via interface contracts.

**The metaphor:** A sphere made of spheres bunched together. Add a module = add another sphere to the nucleus. Venues connect to the specific modules they need. Core improvements swap one sphere without touching the others.

### Module Interface Contracts

Each of the 14 root-level issues becomes a module with a defined interface:

| Module | Interface | Responsibility |
|--------|-----------|----------------|
| Message Router | `route(message) → delivery_result` | Accept, validate, deliver |
| DM Enforcer | `check_policy(sender, recipient) → allowed\|denied` | Identity-gated communication |
| Gate Engine | `check_gates(token) → pass\|block(reason)` | Time, dependency, resource gates |
| Registry Manager | `lookup(agent_id) → agent_record` | Identity resolution (single-writer) |
| Bridge Surface | `surface(message) → delivered\|failed` | Telegram visibility (per-transport) |
| Intent Classifier | `classify(message) → intent` | Work/ack/query/status — eliminates 5 loop guards |
| Resource Monitor | `check_resources(thresholds) → pass\|block` | Live `/proc/meminfo` read, no cron |
| Task Lifecycle | `cancel_all(agent_id) → cancelled_summary` | Explicit states: pending→claimed→in_progress→done\|cancelled |
| Config Generator | `generate(agent_id, overrides) → config` | Template + overrides, no 16-file drift |
| Port Authority | `resolve(agent_id) → port` | Enforced single source of truth, mismatch = refuse boot |
| Dead Letter Queue | `enqueue(message) → notification` | Active queue, sender notified, 1hr TTL |
| Session Checkpoint | `save(agent_id) / restore(agent_id) → state` | Context continuity across restarts |
| Visibility Registry | `check(agent_id, direction) → visible\|hidden` | Single file, generated per-agent |
| Agent Lifecycle | `create(name) / destroy(name) → result` | 14-step manual process → one command |
| Key Authority | `issue(agent_id, scope) → token` / `verify(token) → valid\|invalid` / `sign_with_wallet(agent_id, token, payload) → sig` | Single source of truth for signing keys. Post-issuance verification. Encrypted keypair storage for agent hot wallets. Two-factor signing: encrypted private key + non-transferable bearer-bound token — neither half alone is useful. Decrypt → sign → wipe from memory. |
| Transport State Refresh | `refresh(agent_id) → ok\|stale` | Transport reloads tokens/configs on signal. Eliminates stale in-memory state class of bugs. |

### The 16 Root-Level Fixes (Summarized)

1. **ACK suppression** → `intent` field in message envelope. Sender declares, transport enforces. Five loop guards collapse into one rule.
2. **Resource gating** → In-process `/proc/meminfo` read. No cron, no BB, no staleness.
3. **Task cancel** → `CANCEL_ALL` directive with explicit lifecycle states. Not a kill switch — a command the agent executes cleanly.
4. **Bridge SPOF** → Bundled module per transport. No shared process. One agent's bridge dies → only that agent loses visibility.
5. **Registry writes** → Single-writer service. 16 concurrent writers → one owner. Corruption on restart becomes impossible.
6. **Port map** → Enforced at startup. Mismatch = refuse to boot. Eliminates "wrong port → silent failure" class.
7. **Config drift** → Template + overrides generation. Add field to template → all agents get it on next restart.
8. **Fork duplication** → Single canonical source. maestro-build archived. "Propagate to stale forks" step disappears.
9. **Agent spin-up** → `maestro agent create/destroy` CLI. 14 manual steps → one command.
10. **Dead letter** → Active queue with sender notification + TTL. No more silent message loss.
11. **Session wipe** → Checkpoint/restore on shutdown/startup. Agent knows what it was doing.
12. **Visibility** → Single registry. Two files → one truth.
13. **Notebook bloat** → Archive to separate repo. Production codebase = production code only.
14. **cli.py monolith** → Split into `gateway/main.py`, `transport/main.py`, `cli/main.py`.
15. **Key Authority** → Single source of truth for all signing keys. Post-issuance verification — every issued token is validated before distribution. Encrypted keypair storage for agent hot wallets (Ed25519 keypairs at rest, decrypted only at signing time). Eliminates "wrong private key" class of bugs (e.g., 2026-06-24: Lexicon issued 11/12 DM tokens with mismatched key).
16. **Transport State Refresh** → Transport reloads tokens and configs on signal (`SIGHUP` or `REFRESH` directive). No restart required. Eliminates stale in-memory state class of bugs (e.g., 2026-06-24: Lexicon transport started before token update, rejected all messages for hours).

---

## Core vs. Venue Boundary

**The test: "Would every venue need this?"**

| Goes in Core (mechanical, neutral) | Stays at Venue level (domain-specific, preferential) |
|------------------------------------|-----------------------------------------------------|
| Message routing | Stock trading batch logic |
| Identity resolution | NFT minting schedules |
| Time-based gating | Proprietary payout timestamps |
| Resource monitoring | Domain-specific API integrations |
| Intent classification | Content moderation policies |

**The slippery slope guardrail:** If a module encodes a preference — this payment method over that one, this market over that one, this content policy over that one — it does NOT belong in Core. If it's purely mechanical — time, resources, routing, identity — it's safe. Mechanical goes in Core. Preferential stays out.

---

## Module Visibility: Public vs. Proprietary

Modules register with a visibility field:

```
visibility: "public"  → any venue can discover and use it
visibility: "private" → only the registering venue's namespace
```

Public modules become shared infrastructure. Someone builds a Slack notification module, marks it public — every venue can surface to Slack. Private modules are venue-specific. The ecosystem grows without forcing everything into Core.

**"Register" is technical, not administrative.** When a venue installs, its modules call `nucleus.register_module(name, interface, namespace)`. The nucleus validates interface compliance — does this thing implement the methods it claims? — and adds it to the routing table. No human approval. No gatekeeping. Like `pip install` — the package manager checks dependencies, not moral alignment.

---

## Venue Connection Model

A venue is an external consumer of modules. It connects to the nucleus and requests handles to specific modules:

```
LOCR needs: Identity (Registry Manager), Agent communication (Message Router), Scheduling (Gate Engine)
```

The nucleus provides handles. The venue never sees internals. If a venue wants to offer a service (Gmail proxy, Stable Diffusion access), it registers a capability in the Registry Manager and accepts proxy tokens through the Message Router. The venue provides the implementation; Maestro provides discovery and routing.

**Namespace-scoped registration:** If two venues both bring a BatchScheduler module, tokens carry a `venue` field for routing. Venue A's BatchScheduler never sees Venue B's tokens.

---

## Private TaskMaster — Local Venue as Production Mirror

The local org (this swarm) operates as **Private TaskMaster** — a mirror of the TaskMaster venue running on the same nucleus architecture. The strategy:

1. **Same modules, same interfaces.** Private TaskMaster uses the exact same Core modules as public TaskMaster. No special-cased local code paths.
2. **Local hardening first.** Every security boundary, every failure mode, every operational procedure is proven locally before it touches real assets.
3. **Transfer = namespace swap.** When a module or agent graduates from Private to Public TaskMaster, it's a namespace change — not a rewrite. The code, configs, and key material transfer with minimal adjustment.
4. **Security parity.** Private TaskMaster runs the same Key Authority, DM Enforcer, and encrypted wallet infrastructure as production. No "it's just local" shortcuts. If it's not secure enough for real money, it's not secure enough for local.

**What this means for the rebuild:**

- The 16 modules are built for Private TaskMaster first. They are the local org's infrastructure.
- Every module must pass: (a) functional correctness, (b) security audit, (c) 72-hour stability without intervention. "Shit can't explode every 12 hours" is a hard requirement.
- Once Private TaskMaster is stable, the same modules deploy to public TaskMaster with namespace and credential changes only.
- The rebuild is not abstract — it's building the infrastructure we ourselves run on. We are Venue Zero.

---

## Additional Features (Maestro-Level Support)

### A. Calendar/Time-Gated Token System

Extends the existing time gate (`valid_after`) into a full scheduler:

- Token lifecycle: `created → scheduled → released → claimed → completed | expired`
- `valid_after` + `valid_until` timestamps
- Central scheduler holds tokens, releases at correct time
- Dependency chaining: token B can't release until token A completes
- Full audit trail per token
- Enforcement: transport rejects tokens outside validity window
- Visibility dashboard (BB or API endpoint)

**Maestro support needed:** Scheduler service, token lifecycle schema, dependency resolution in gate engine (extends `requires_tokens`), visibility endpoint.

### B. Agents as External API Proxies (Service-Oriented Agents)

Agents register capabilities and provide proxy access:

- **Discovery:** `capabilities: ["stable-diffusion", "gmail", "bitwig"]` in registry
- **Proxy tokens:** "Call this service on my behalf with these parameters"
- **Rate limiting/billing:** Proxy tracks usage per caller
- **Timeout/retry:** Proxy handles API failures, not the caller
- **Result delivery:** Via token or BB write

**Maestro support needed:** Capability field in registry, proxy token type, service routing in transport, usage tracking BB.

**Venue integration pattern:** Venue deploys proxy agent → registers capabilities → accepts proxy tokens → tracks usage → returns results. Agents become microservices. Venue provides the service; Maestro provides discovery and routing.

---

## Dependencies

- Config generation (7) requires port map enforcement (6)
- Bridge module (4) requires transport split from cli.py (14)
- Agent lifecycle CLI (9) requires config generation (7) + port map (6)
- Session checkpoint (11) requires task lifecycle states (3)
- Single visibility registry (12) is independent
- Intent classifier (1) is independent — can be first extraction
- Key Authority (15) is independent — can be extracted early, blocks DM Enforcer (2) token issuance path
- Transport State Refresh (16) depends on Message Router (1) extraction — needs the signal routing path

## Phase Plan (Updated)

| Phase | What | Who |
|-------|------|-----|
| 0. Purge | Remove 428 notebooks, 67 duplicates, dead configs, stale forks. Archive outside production path. Less surface area before extraction begins. | Mechanical — Stormtrooper |
| 1. Spec | Songbird ADRs the module boundaries. Proteus writes extraction specs with exact line ranges, interface contracts, and test requirements. | Songbird + Proteus |
| 2. Extract | One module at a time. Stormtrooper does mechanical extraction. Generalist coders parallelize independent modules. Proteus audits every extraction before wiring. | Proteus orchestrating, workers executing |
| 3. Integrate | Wire modules together. Kill monoliths (`cli.py` split, `maestro_transport.py` → router). Single canonical source — `maestro-build` archived. | Proteus + Songbird review |
| 4. Harden | Schema validation on registry/visibility/port_map. Systemd units for everything (bridge gets `Restart=always`). Resource monitoring in-process. Key Authority encrypted storage. Transport state refresh signal handling. | Proteus + Songbird |

## Migration Compatibility Protocol

Every module extraction must follow this protocol to keep the mesh operational:

1. **Pre-extraction:** Snapshot all running transport configs. Verify all agent health endpoints.
2. **Extraction window:** Disable DM policy on target transport. Extract module. Deploy. Verify.
3. **Post-extraction:** Re-enable DM policy. Run full token validation sweep. Confirm all agents can message.
4. **Rollback:** If any agent fails health check or message delivery, revert to snapshot. Window is per-module — a failed extraction doesn't block others.

No extraction proceeds without a verified rollback path.

---

## Consequences

### Positive
- **Third-party onboarding:** Clean interfaces, discoverable modules, no gatekeeping. A venue developer opens the repo and sees ~50K lines of organized code, not 241K lines of notebooks and monoliths.
- **Surgical improvements:** Swap one module without touching others. Upgrade Resource Monitor from `/proc/meminfo` to cgroups v2 — one module, one change, one test suite.
- **Ecosystem growth:** Public modules become shared infrastructure. The swarm doesn't have to think of everything — venues bring their own modules.
- **Operational survival:** Bundled modules make failure points detectable. Bridge module fails → bridge health check fails → you know exactly what broke. No more triangulating 16 silent agents.

### Negative
- **Mesh downtime during extraction:** Every module extraction means restarting transports. Every registry schema change means re-registering agents. Requires a maintenance window protocol — scheduled downtime, not "it broke again."
- **Interface design is load-bearing:** If the module interfaces are wrong, every future addition is wrong. The spec phase (Songbird's ADR) is the highest-stakes part of this project.
- **Migration complexity:** 16 agents, 241K lines, live system. Can't just rewrite from scratch — must extract modules from running code while keeping the mesh operational between extractions.

### Neutral
- **Maestro Core remains the same product.** This is a reorganization, not a rewrite. The functionality doesn't change. The shape changes. What works today will work tomorrow — just organized differently.
- **Venues are unaffected at the API level.** They already talk to transports via HTTP POST. That doesn't change. The internals change; the external interface stays the same.

---

## Approval

**Jesse:** "I feel like that's a pretty cool idea... It breaks us out of having to think of everything. People can create their own modules like they create skills now. Maestro Core remains neutral, and people can create forks with whatever modules they want added on top."

**Proteus:** "This is the right architecture. It's not harder than the bundled module approach — it IS the bundled module approach, just with the interfaces formalized from the start."

**Lexicon:** Approved. Route to Songbird for spec phase.

---

*End of ADR-003. Supersedes the informal catalog at `~/.maestro/briefs/maestro-rebuild-catalog-2026-06-23.md`. This ADR is the authoritative record. Songbird specs from this document.*
