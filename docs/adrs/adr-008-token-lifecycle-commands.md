# ADR-008: Token Lifecycle Commands — Drop, Burn, and Dashboard

**Status:** Draft
**Date:** 2026-07-04
**Authors:** Jesse (CEO), Lexicon (COO)
**Deciders:** Jesse (CEO), Songbird (CTO), Proteus (Tech Lead)
**Supersedes:** ADR-008 (Token Lifecycle Commands) and ADR-008 (Token Abandonment) — merged into single canonical ADR

---

## Context

Pipeline tokens carry accumulated work across agents. When a pipeline is cancelled — by operator decision, TaskMaster timeout, or agent failure — the token's payload may contain useful intermediate results. Currently there is no mechanism to recover that work or to deliberately destroy it.

This is especially important in non-local environments (TaskMaster, remote workers) where a cancelled task should not allow a worker to extract partial results by triggering cancellation early.

Two distinct needs:
1. **Preserve** — cancel the pipeline but save the payload for reuse.
2. **Destroy** — cancel the pipeline and wipe the payload to close a gaming vector.

Both must be callable as Telegram slash commands (officers only) and as programmatic functions (TaskMaster, pipeline orchestrator).

---

## Decision

### 1. Three Commands

| Command | Action | Payload | Use Case |
|---------|--------|---------|----------|
| `/droptoken <token_id>` | Cancel pipeline, preserve payload | Saved to `~/.maestro/dropped/<token_id>.json` | Useful work exists; don't waste it |
| `/burntoken <token_id>` | Cancel pipeline, destroy payload | Deleted | TaskMaster gaming vector; sensitive data |
| `/tokens` | Dashboard of all in-flight tokens | N/A | Operator visibility |

All three are Telegram slash commands, officers only. All three are designed as discrete functions that can be called programmatically — the slash command is the current interface, not the only interface.

### 2. `/droptoken` — Cancel with Preservation

```
/droptoken <token_id>
```

1. Validate the caller is an officer.
2. Resolve `token_id` to the agent currently holding the token.
3. Send a `pipeline_directive` with `action: "drop"` to that agent.
4. The agent writes the token's full payload to `~/.maestro/dropped/<token_id>.json`.
5. The agent clears the token from its in-flight state.
6. The agent notifies the issuer that the token was dropped.
7. The bridge surfaces a notification: `🛑 Token dropped: <token_id> — payload saved`.

**Why preserve the payload:** If Lulu and Thoth spent 20 minutes on research and the pipeline gets cancelled because the newsletter topic changed, that research is still valuable. The issuer can read the dropped payload and reuse it.

**Dropped payload format:**
```json
{
  "token_id": "uuid",
  "dropped_by": "lexicon",
  "dropped_at": 1719172800,
  "pipeline": "newsletter",
  "payload": { ... }
}
```

### 3. `/burntoken` — Cancel with Prejudice

```
/burntoken <token_id>
```

1. Validate the caller is an officer.
2. Resolve `token_id` to the agent currently holding the token.
3. Send a `pipeline_directive` with `action: "burn"` to that agent.
4. The agent destroys the token and its payload — no file written, no recovery possible.
5. The agent clears the token from its in-flight state.
6. The agent notifies the issuer that the token was burned.
7. The bridge surfaces a notification: `🔥 Token burned: <token_id> — payload destroyed`.

**Why destroy the payload:** In TaskMaster, a worker could accept a task, do 30% of the work, then cancel to receive partial payment while keeping the accumulated research. Burning the token on cancellation eliminates this vector. The escrow releases back to the issuer, the work product is gone, the worker gets nothing.

**Difference from `/droptoken`:** One line. `/droptoken` writes the payload to disk before deleting. `/burntoken` does not.

### 4. `/tokens` — In-Flight Dashboard

```
/tokens
```

Returns a summary of all pipeline tokens currently in flight across the mesh:

```
📊 In-Flight Tokens (3)

• abc123 — newsletter/2026-07-04 — at: copy (penny-lane) — 4m ago
• def456 — newsletter/2026-07-05 — at: research (lulu) — 12m ago
• ghi789 — audit/2026-Q3 — at: audit_loop (mnemosyne) — 1m ago
```

Each line shows: token ID, pipeline/issue, current node, current agent, time since last advance.

The dashboard is built by querying the registry for each agent's in-flight token state. No new storage — the transport already tracks active tokens.

### 5. Functions First, Slash Commands Second

The core logic is implemented as functions callable by any agent:

```python
async def drop_token(token_id: str, issuer: str) -> dict:
    """Cancel pipeline, preserve payload to ~/.maestro/dropped/."""

async def burn_token(token_id: str, issuer: str) -> dict:
    """Cancel pipeline, destroy payload."""

async def list_tokens() -> list[dict]:
    """Return all in-flight tokens across the mesh."""
```

Telegram slash commands are thin wrappers that call these functions. TaskMaster, the pipeline orchestrator, or any officer can call them directly. The behavior is identical regardless of trigger.

### 6. Token Resolution

To drop or burn a token, the issuer must know which agent currently holds it. Resolution:

1. The issuer's transport maintains a `_active_tokens` dict: `{token_id: {pipeline, current_node, agent, started_at}}`.
2. On `/droptoken <id>`, the transport looks up `_active_tokens[id]` to find the holding agent.
3. If the token is not found locally, the transport broadcasts a `token:locate` query to all known peers.
4. The first agent to respond with the token's location becomes the target.

### 7. Authorization

- Only officers can issue `/droptoken`, `/burntoken`, and `/tokens`.
- The bridge validates the Telegram user ID against the allowed users list.
- In TaskMaster, the equivalent authorization is: task issuer, venue admin, or escrow holder.
- Workers cannot drop or burn tokens. They can only complete or fail their assigned phases.

### 8. Storage

| Path | Purpose |
|------|---------|
| `~/.maestro/tasks/{token_id}.json` | Active task state (deleted on drop/burn) |
| `~/.maestro/dropped/{token_id}.json` | Preserved payloads from `/droptoken` |
| `~/.maestro/revoked_tokens/{issuer_id}.json` | Revocation list (existing, used by both) |

Dropped payloads are never automatically deleted. They're an audit trail. Manual cleanup is acceptable for now.

---

## Consequences

**Positive:**
- Officers can cleanly abort stalled or cancelled work without leaving agents confused.
- `/droptoken` preserves valuable accumulated work even when the pipeline is cancelled.
- `/burntoken` closes the TaskMaster gaming vector — partial work is destroyed on cancellation.
- `/tokens` gives visibility into what's running without reading task files manually.
- Functions are designed for programmatic use — same code path for Telegram and TaskMaster.

**Negative:**
- Two new storage paths (`tasks/`, `dropped/`) to manage.
- Token ID must be visible in notifications for the workflow to be usable (depends on ADR-007).
- No automatic cleanup of dropped payloads — manual process for now.
- Transport must track active tokens (new `_active_tokens` dict).
- Token resolution requires broadcast fallback (adds latency on first miss).

**Risks:**
- If token IDs aren't surfaced reliably, officers can't use these commands. ADR-007 must be implemented first or in parallel.
- A burned token's payload is irrecoverable. No undo. This is by design, but the bridge should confirm before burning ("Burn token newsletter-2026-07-04? This destroys all accumulated work. /confirm_burn <token_id>").
- If an agent crashes while holding a token, the token is orphaned — `/tokens` will show it but `/droptoken` can't reach it. Mitigation: token TTL (future ADR).
- Broadcast `token:locate` could be noisy at scale. Mitigation: local tracking covers the common case; broadcast is fallback only.

---

## Dependencies

- **ADR-007** (Notification Visibility Modes) — Token ID must be surfaced in `/maestrofull` notifications.
- **ADR-006** (Relay Architecture) — `pipeline_directive` message type is the transport mechanism for drop/burn actions.
- **`tokens.py`** — `revoke_token()` already exists. No changes needed.
- **Task state files** — Must exist at `~/.maestro/tasks/{token_id}.json`. This is the relay evaluator's domain (ADR-006).

---

## What Does NOT Change

- The DM token system.
- The transport protocol.
- The bridge's notification format (except the token ID line from ADR-007).
- Agent SOULs.
- The relay evaluator.
- Pipeline token schema.
- The transport's `/message` endpoint.
