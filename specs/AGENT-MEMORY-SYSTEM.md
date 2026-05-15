# Maestro Agent Memory System

**Version:** 1.0-draft  
**Status:** Proposed — awaiting Proteus implementation  
**Owner:** Songbird (CTO)  
**Scope:** Cross-agent infrastructure — applies to all agents on the mesh  

---

## Purpose

Two problems this solves:

1. **Jesse needs a human-readable survey** of what every agent is doing without reading
   technical logs. `/work proteus` should read like a changelog, not a stack trace.

2. **Agents need to survive compaction.** When a context window resets, the agent
   should be able to reconstruct "what was I doing and why" in under 10 seconds,
   without Jesse having to re-brief them.

---

## Three-Tier Architecture

```
Tier 1 — Work Log       (technical, granular, permanent)
Tier 2 — Blackboard     (plain English, rolling 4h window, human-readable)
Tier 3 — Task Memory    (LLM summary, updated every 4h, survives compaction)
```

### Tier 1: Work Log

- **What:** Every task start/finish with full technical detail
- **Format:** JSON entries — timestamps, task IDs, durations, error codes, commit hashes
- **Written by:** Agent, on every `task_start` / `task_finish` event
- **Pruned:** Never during active task. Archived (not deleted) at task completion.
- **Used by:** Agents for self-diagnosis. Not exposed to Jesse directly.

```json
{
  "type": "task_finish",
  "agent_id": "proteus",
  "description": "Fix LocalRegistry write clobber",
  "started_at": 1747260000000,
  "finished_at": 1747263600000,
  "duration_sec": 3600,
  "commit": "bef9aa7",
  "test_result": "196/196 pass",
  "notes": "Root cause: concurrent flock on shared registry file"
}
```

---

### Tier 2: Blackboard (Rolling 4h Window)

- **What:** Plain-English activity entries — readable by Jesse and any agent
- **Format:** Short human sentences + timestamp. No jargon.
- **Written by:** Agent, on task start/finish — but in plain English
- **Pruned:** Rolling window, entries older than 4 hours are dropped
- **Used by:** `/work [agent]`, `/workall`, and agents filling gaps after compaction

**Entry format:**

```json
{
  "agent_id": "proteus",
  "ts": 1747263600000,
  "ts_human": "2026-05-15 11:30am",
  "status": "finished",
  "summary": "Fixed bug that caused messages to get routed to the wrong agent"
}
```

**What `/work proteus` shows:**

```
Proteus — last 4h

11:51am  Started: Revising shared memory blackboard schema
         Status:  In progress

11:30am  Started: Fixing 2 failed Connection Broker tests
         Finished: 11:50am (20 min)
         Fixed bug that caused messages to get routed to the wrong agent

10:15am  Started: Porting NonceSet replay protection to TypeScript
         Finished: 11:28am (73 min)
         Replay protection now works in both Python and TypeScript transports
```

**What `/workall` shows:** Same format, all agents, most recent first, grouped by agent.

---

### Tier 3: Task Memory

- **What:** LLM-generated plain-English summary of work log activity
- **Written by:** Each agent via cron, every 4 hours, self-summarizing their own work log
- **Model:** Agent's own model (Ollama for Proteus/Solder — zero marginal cost)
- **Format:** Markdown narrative, ~200-400 words
- **Stored at:** `~/.maestro/memory/<agent_id>/task_memory_<timestamp>.md`
- **Pruned:** Not pruned during active task. Archived (not deleted) at task completion.
- **Used by:** Agent self-orientation after compaction

**Example Task Memory entry:**

```markdown
## Task Memory — Proteus — 2026-05-15 12:00pm

Working on Maestro Alpha for grant submission (target May 20).

Completed this session:
- Fixed LocalRegistry write clobber in TypeScript transport (commit bef9aa7).
  Root cause was concurrent flock on a shared file. All 196 tests now green.
- Ported NonceSet replay protection from Python to TypeScript.
  Covers timestamp drift, nonce deduplication, TTL boundary.

Currently working on:
- Revising the blackboard schema for the new task-tracking format.

Blocked on: nothing.

Next up: /work output formatting, then hand off to Solder for commit cleanup.
```

---

## Agent Self-Orientation After Compaction

When an agent's context resets (compaction, restart, new session):

```
1. Load latest Task Memory
   → "Here's what I was working on for the last N hours"

2. If memory timestamp is stale (gap > 30 min):
   → Read BB entries since last memory timestamp
   → "Here's what happened in the gap"

3. If granular detail needed:
   → Read work log for specific task
```

This means worst case: agent loses the last 30 minutes of micro-context. They know
exactly what they were working on, where they left off, and what's next. Jesse does
not need to re-brief them.

---

## Implementation Spec

### New Message Types (Transport Layer)

Add to `handle_message` in `maestro_transport.py` and TypeScript equivalent:

| Type | Direction | Description |
|------|-----------|-------------|
| `task_start` | Agent → Transport | Writes Tier 1 (technical) + Tier 2 (plain English) entry |
| `task_finish` | Agent → Transport | Updates Tier 1 entry, appends Tier 2 finished entry |
| `bb_query` | Any → Transport | Returns BB entries for one or all agents |
| `memory_write` | Agent → Transport | Stores a Task Memory snapshot |
| `memory_read` | Agent → Transport | Retrieves latest Task Memory for an agent |

### BB Pruning

- BB entries older than 4 hours are dropped on every write
- No explicit prune endpoint needed — write handler prunes inline
- On task completion, BB entries are NOT archived (they expire naturally)
- Work log and Task Memory ARE archived on task completion

### Cron: Task Memory Update

Each agent runs a local cron every 4 hours:

```
1. Read work log entries since last Task Memory timestamp
2. LLM self-summarize (agent's own model — no external cost)
3. Write to ~/.maestro/memory/<agent_id>/task_memory_<ts>.md
4. POST memory_write to own transport endpoint
```

### /work and /workall Commands

Update gateway `handle_worklog_query` to read from BB (Tier 2), not raw work log.

```
/work          → BB entries for the calling agent's session
/work proteus  → BB entries for Proteus (last 4h)
/workall       → BB entries for all registered agents (last 4h)
```

Consider renaming to `/bb` and `/bball` — clearer semantics, avoids confusion with
the technical work log. Keep `/work` as an alias for backward compat.

### Task Completion / Archival

When an agent marks a task complete:
1. Archive work log → `~/.maestro/archive/<agent_id>/<task_id>/work_log.json`
2. Archive Task Memory snapshots → same directory
3. Clear active work log
4. BB entries expire naturally (4h TTL)

---

## What This Does NOT Do

- **No on-chain storage.** All memory is local files.
- **No cross-agent memory merging.** Each agent owns its own memory.
- **No automatic task detection.** Agents must explicitly call `task_start` / `task_finish`.
  This is intentional — implicit detection would be unreliable.
- **No Jesse-facing memory writes.** Jesse reads via `/work` and `/workall` only.

---

## Roadmap Slot

Scheduled before economic layer (Phase 4). Suggested slot: **Phase 2.5**, after
`/work` formatting polish and before wallet identity work.

| Phase | Work | Owner |
|-------|------|-------|
| 2.5a | BB schema + `task_start`/`task_finish` message types | Proteus |
| 2.5b | `/work` + `/workall` output formatting (reads from BB) | Proteus |
| 2.5c | Task Memory cron (4h self-summarization) | Proteus |
| 2.5d | Compaction recovery flow (load memory → fill from BB) | Proteus |
| 2.5e | `/bb` and `/bball` aliases, backward compat `/work` | Proteus |

Estimated total: 1.5–2 days.

---

## Open Questions

1. Should `task_start` require an explicit task ID, or auto-generate one?
2. Do we want a `task_cancel` type (task abandoned, not finished)?
3. Should Task Memory be surfaced via `/memory [agent]` command, or only used internally?
4. Archive trigger: explicit `task_complete` message, or inferred from agent going quiet?

---

*Drafted: 2026-05-15*  
*Author: Songbird (CTO)*  
*For implementation by: Proteus (Tech Lead)*
