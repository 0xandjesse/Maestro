# ADR-011: Configuration Convergence — Eliminating the Restart Cascade

**Status:** Draft
**Date:** 2026-07-05
**Authors:** Jesse (CEO), Proteus (Tech Lead)
**Deciders:** Jesse (CEO), Songbird (CTO), Proteus (Tech Lead)
**Supersedes:** None (new concern)

---

## Context

On 2026-07-04, a routine visibility slash-command deployment triggered a cascade of failures that consumed an entire day. The chain:

1. Lexicon's skills registry was updated with new slash commands
2. Lexicon's transport didn't pick them up — hadn't restarted
3. Restarting Lexicon's transport revealed a stale gateway process
4. Restarting the gateway revealed stale formatting (transport loaded old formatter)
5. Restarting the transport again fixed formatting for Lexicon
6. Songbird then returned 403 — his transport had been running since June 29

Every failure had the same root cause: **"It'll pick it up next restart."**

This phrase is the smell. It means something important is initialized once and never refreshed. The system has multiple mutable pieces of state — skills registries, formatters, gateway processes, transport configs, visibility modes — and they do not converge automatically after a change.

This is not a coding problem. It is a **configuration convergence problem**. It is the class of bug that emerges when persistent services outgrow manual orchestration.

The user's "Hello World" moment — watching two agents communicate for the first time — is the Trust Surface. If that moment is a cascade of 403s and stale processes, confidence in the entire architecture is lost before it begins.

---

## Decision

**The Maestro runtime SHALL implement a Configuration Convergence Protocol that ensures all mutable state converges to the latest version without manual restart cascades.**

This protocol has four components:

1. **Hot Reload** — Components that load configuration at startup SHALL support reloading without process restart
2. **Health Verification** — Every component SHALL expose a health endpoint that reports its configuration version and dependency status
3. **Convergence Check** — A single command SHALL verify that all components are running the same configuration version
4. **Restart Sequencing** — When restarts are unavoidable, they SHALL be automated in dependency order with pre- and post-verification

The principle: **No user should ever need to know the phrase "transport has been up since June 29."**

---

## The Convergence Problem, Decomposed

### What State Is Mutable?

| State | Where It Lives | How It's Loaded | Refresh Mechanism |
|-------|---------------|-----------------|-------------------|
| Skills registry | `~/.hermes/profiles/<agent>/skills/` | Gateway at startup | Gateway restart |
| Slash command discovery | `scan_skill_commands()` | Gateway at startup | `/reload_skills` or gateway restart |
| Transport config | `~/.maestro/configs/<agent>.json` | Transport at startup | Transport restart |
| Gateway bridge formatter | `maestro_gateway_bridge.py` | Bridge at startup | Bridge restart |
| Visibility modes | `~/.hermes/maestro_visibility.json` | Bridge on each request | Immediate (file read) |
| Bridge visibility | `~/.maestro/bridge_visibility.json` | Bridge on each request | Immediate (file read) |
| Agent emojis | `~/.maestro/agent_emojis.json` | Bridge at startup | Bridge restart |
| DM tokens | `~/.maestro/dm_tokens/` | Transport on each message | Immediate (file read) |
| Registry entries | `~/.maestro/registry.json` | Transport on each message | Immediate (file read) |
| Gateway process | systemd unit | systemd at boot | `systemctl restart` |
| Transport process | systemd unit | systemd at boot | `systemctl restart` |

### The Restart Cascade, Mapped

```
Skills updated
  → Gateway doesn't know (loaded at startup)
    → Restart gateway
      → Gateway now has new skills
  → Transport doesn't know about new slash commands (loaded at startup)
    → Restart transport
      → Transport now picks up new commands
  → Bridge formatter is stale (loaded at startup)
    → Restart bridge
      → Bridge now formats correctly
  → Other agents' transports are stale (loaded at startup, some for days/weeks)
    → Restart each agent's transport
      → All agents now converged
```

Every arrow is a manual step. Every step is a potential failure point. Every failure erodes trust.

### Why "Read on Every Request" Isn't Enough

Some state (visibility modes, DM tokens, registry) is already read on every request. This is correct for data that changes independently of code. But skills, formatters, and config parsers are **code-level concerns** — they change when the codebase changes, and reloading them requires re-importing Python modules or re-parsing directory trees. These are the states that need hot reload.

---

## The Four Components

### 1. Hot Reload

Components that load configuration at startup SHALL support a `POST /reload` endpoint that re-reads their configuration without process restart.

| Component | What It Reloads | Endpoint |
|-----------|----------------|----------|
| Gateway | Skills registry, slash commands | `POST /reload` (already exists as `/reload_skills`) |
| Transport | Config file, formatter modules | `POST /maestro/reload` |
| Bridge | Agent emojis, formatter modules | `POST /maestro/reload` |

**Transport `/maestro/reload` behavior:**
1. Re-read config JSON from disk
2. Re-import formatter modules (invalidate Python module cache)
3. Re-read agent emojis
4. Log the reload with old and new version hashes
5. Return `{"ok": true, "config_hash": "<sha256>", "reloaded": ["config", "formatter", "emojis"]}`

**Bridge `/maestro/reload` behavior:**
1. Re-read agent emojis from `~/.maestro/agent_emojis.json`
2. Re-import formatter modules
3. Return `{"ok": true, "reloaded": ["emojis", "formatter"]}`

**Gateway `/reload_skills` (existing):**
- Already exists. Ensure it also triggers slash command rediscovery.

### 2. Health Verification

Every component SHALL expose a `GET /health` endpoint that returns:

```json
{
  "ok": true,
  "component": "maestro-transport",
  "agent_id": "songbird",
  "uptime_seconds": 518400,
  "config_hash": "a1b2c3d4",
  "dependencies": {
    "gateway": {"reachable": true, "version": "4.2.1"},
    "bridge": {"reachable": true, "port": 8644},
    "registry": {"entries": 18, "last_updated": "2026-07-05T02:00:00Z"}
  },
  "version": "3.2"
}
```

The `config_hash` is a SHA256 of the config file contents. This is the convergence signal — if two transports have different config hashes, they are not converged.

**Existing health endpoints:**
- Transport: `GET /health` — returns `{"ok": true, "agentId": "...", "uptime": ..., "seen_keys": ...}`. Extend with `config_hash` and `dependencies`.
- Bridge: `GET /health` — returns `{"ok": true, "service": "maestro-gateway-bridge", "version": "0.1"}`. Extend with `config_hash`.
- Gateway: `GET /health` — already exists. Extend with `config_hash`.

### 3. Convergence Check

A single command — `maestro-converge` — that verifies all components are running the same configuration:

```bash
maestro-converge
```

**Behavior:**
1. Read the canonical config for each agent from `~/.maestro/configs/`
2. Compute the expected config hash for each agent
3. Query each agent's transport `/health` endpoint
4. Query the bridge `/health` endpoint
5. Query each agent's gateway `/health` endpoint
6. Compare expected vs. actual config hashes
7. Report convergence status

**Output:**

```
agent           transport   gateway    bridge    status
─────           ─────────   ───────    ──────    ──────
lexicon         ✓ a1b2c3    ✓ a1b2c3   ✓         converged
songbird        ✗ d4e5f6    ✓ a1b2c3   ✓         STALE (transport: 6d old)
proteus         ✓ a1b2c3    ✓ a1b2c3   ✓         converged
mnemosyne       ✓ a1b2c3    ✓ a1b2c3   ✓         converged
lulu            ✓ a1b2c3    —          ✓         converged (no gateway)
bridge          —           —          ✓ a1b2c3   converged

2/5 agents STALE. Run: maestro-converge --fix
```

**Options:**
- `--fix` — Automatically reload or restart stale components
- `--json` — Machine-readable output for watchdog cron jobs
- `--agent <id>` — Check a single agent

### 4. Restart Sequencing

When hot reload is insufficient and a restart is required, `maestro-converge --fix` SHALL restart components in dependency order:

```
Restart order:
  1. Bridge (no dependencies)
  2. Transports (depend on bridge for surface)
  3. Gateways (depend on transports for message delivery)
```

**For each component:**
1. `systemctl restart <unit>`
2. Poll `/health` until reachable (max 30s)
3. Verify `config_hash` matches expected
4. If verification fails, log and continue to next component
5. Report final convergence status

**Safety:**
- Never restart all components simultaneously
- Always verify each component before proceeding to the next
- If a component fails to converge after restart, stop and report — do not cascade

---

## The Trust Surface Test

The "Hello World" path — two agents communicating — SHALL be verifiable with a single command:

```bash
maestro-smoke-test
```

**Behavior:**
1. Select two agents (default: lexicon → songbird)
2. Send a test message: `Subject: Communication Test`
3. Verify the message is delivered (HTTP 200 from transport)
4. Verify the message surfaces in Telegram (bridge returns `ok: true`)
5. Verify the recipient's transport acknowledges receipt
6. Report: `✓ Maestro communication layer operational`

This test SHALL run:
- After every `maestro-converge --fix`
- After every `install.sh` run
- On demand via `maestro-smoke-test`
- Automatically via a watchdog cron job every 30 minutes

If this test fails, nothing else matters. The Trust Surface is broken.

---

## Implementation Sequence

### Phase 1: Health Endpoint Extension (Immediate)

Extend existing `/health` endpoints with `config_hash` and `dependencies`. This is the foundation — without it, convergence cannot be measured.

**Files to modify:**
- `maestro_transport.py` — `handle_health()` (line ~880)
- `maestro_gateway_bridge.py` — `_health_handler()` (line ~424)

**Final steps after Phase 1:**
```bash
# Restart transports to pick up new health endpoint
for agent in lexicon songbird proteus mnemosyne lulu penny-lane stormtrooper; do
    systemctl --user restart maestro-transport-$agent.service
done
# Restart bridge
systemctl --user restart maestro-bridge.service
# Verify
curl -s http://127.0.0.1:3844/health | jq .config_hash
curl -s http://127.0.0.1:8644/health | jq .config_hash
```

### Phase 2: Hot Reload Endpoints

Add `POST /maestro/reload` to transport and bridge. Wire gateway's existing `/reload_skills` into the convergence protocol.

**Files to modify:**
- `maestro_transport.py` — new `handle_reload()` method
- `maestro_gateway_bridge.py` — new `_reload_handler()`

**Final steps after Phase 2:**
```bash
# Restart transports and bridge to pick up new endpoints
for agent in lexicon songbird proteus mnemosyne; do
    systemctl --user restart maestro-transport-$agent.service
done
systemctl --user restart maestro-bridge.service
# Test hot reload
curl -s -X POST http://127.0.0.1:3844/maestro/reload | jq .
curl -s -X POST http://127.0.0.1:8644/maestro/reload | jq .
```

### Phase 3: Convergence Tool

Build `maestro-converge` as a standalone script in `~/.local/bin/`.

**New file:** `~/.local/bin/maestro-converge`

**Behavior:**
- Reads `~/.maestro/configs/` for expected config hashes
- Queries all agent `/health` endpoints (ports from `~/.maestro/port_map.json` or vault)
- Queries bridge `/health`
- Reports convergence status
- `--fix` flag triggers sequenced restarts

**Final steps after Phase 3:**
```bash
chmod +x ~/.local/bin/maestro-converge
maestro-converge
maestro-converge --fix  # test on a single stale agent first
```

### Phase 4: Smoke Test + Watchdog

Build `maestro-smoke-test` and wire it into a cron job.

**New file:** `~/.local/bin/maestro-smoke-test`

**Cron job:**
```bash
# Every 30 minutes, verify the Trust Surface
cronjob create --name "maestro-smoke-test" --schedule "*/30 * * * *" \
  --prompt "Run maestro-smoke-test. If it fails, run maestro-converge --fix and retry. Report results to Jesse."
```

**Final steps after Phase 4:**
```bash
chmod +x ~/.local/bin/maestro-smoke-test
maestro-smoke-test
# Verify cron job is active
cronjob list | grep maestro-smoke-test
```

---

## What Does NOT Change

- Message delivery. Convergence failures suppress notifications, not messages.
- The `Subject:` line requirement.
- DM token validation.
- Registry structure.
- The composition model (Grammar/Capabilities/Policies/Environments).
- The visibility slash commands (`/maestrofull`, `/maestroshort`, `/maestrooff`).

---

## Consequences

**Positive:**
- "It'll pick it up next restart" is eliminated as a user-facing concept
- The Trust Surface (first agent-to-agent message) becomes reliably verifiable
- Operators can verify system health with a single command
- Stale components are detected automatically, not discovered by 403s
- The restart cascade is automated and sequenced, not manual and error-prone
- New users never learn the phrase "transport has been up since June 29"

**Negative:**
- Hot reload adds complexity to transport and bridge (new endpoints, module cache invalidation)
- Health endpoint extension requires coordinated rollout (all transports must be restarted)
- Convergence tool adds a new operational dependency

**Risks:**
- Hot reload of Python modules is fragile — `importlib.reload()` has known edge cases with stateful modules. Mitigation: if hot reload fails, fall back to restart sequencing.
- Config hash computation must be deterministic — same file, same hash. Mitigation: SHA256 of raw file bytes, not parsed JSON.
- If the convergence tool itself has a bug, it could report false positives (all clear when components are stale). Mitigation: the smoke test is the ground truth — if `maestro-smoke-test` passes, the system is converged regardless of what `maestro-converge` reports.

---

## Open Questions

1. Should hot reload be automatic (file watcher) or on-demand (POST /reload)? Leaning toward: on-demand. File watchers add complexity and can trigger mid-operation reloads. The convergence tool triggers reloads explicitly when needed.

2. Should `maestro-converge --fix` restart gateways? Gateways are the heaviest component to restart (they kill active LLM sessions). Leaning toward: gateways are restarted last, and only if their config hash is stale. A `--no-gateway` flag skips gateway restarts for safety.

3. Should the smoke test use real agents or a dedicated test pair? Leaning toward: real agents (lexicon → songbird) because the point is to verify the production path. A test pair would verify a path nobody uses.

4. What's the config hash for agents that don't have a config file (implicit agents like Coding Crew)? Leaning toward: agents without config files are excluded from convergence checks. They're ephemeral workers, not persistent services.

---

## References

- [ADR-004: Local Org as Venue Zero](./ADR-004-local-org-venue-zero.md) — The Environment model
- [ADR-007: Maestro Notification Visibility Modes](~/.hermes/profiles/songbird/cache/documents/doc_5d7a92af9e07_ADR-007-maestro-notification-visibility-modes.md) — The visibility system that triggered the cascade
- [Maestro Composition Model](../maestro-composition-model.md) — The four-layer architecture
- [Maestro Transport Layer](~/Projects/Maestro/code/runtime/maestro_transport.py) — Transport implementation (2305 lines)
- [Maestro Gateway Bridge](~/Projects/Maestro/code/runtime/maestro_gateway_bridge.py) — Bridge implementation (466 lines)
- [Systemd units](~/.config/systemd/user/maestro-*.service) — 19 transport/bridge/event-bus/visibility/renderer services
