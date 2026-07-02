# Phase 0 — Purge Stale Artifacts
## Sub-spec for Proteus (self-execute)

### Task
Remove stale forks and dead configs from the Maestro repo before extraction begins.

### Items
1. **Remove `maestro-protocol-backup-v0.2.0/`** — 7 files, stale fork
2. **Remove `live/maestro_transports/{lulu,stormtrooper}/`** — stale transport copies (8 files each)
3. **Archive dead configs** — agents not in active swarm: `cactus-jack`, `cee-lo`, `chatterbox`, `mondo-gecko`, `zulu`, `uatu`, `thoth`, `keystone` (move to `~/.maestro/configs/archive/`)

### Success Criteria
- Stale forks deleted
- Dead configs archived (not deleted — recoverable)
- Active configs untouched
- `git status` shows clean removals
