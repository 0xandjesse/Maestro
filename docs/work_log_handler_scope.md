# Work Log Handler — Scope & Design Draft

**Author:** soldier  
**Date:** 2026-05-15  
**Status:** DRAFT — pending Proteus review  

---

## 1. Problem

Work logs are written on every inbound message (`_write_work_log`) and queryable via HTTP POST `/maestro/worklog/query`. However, there is **no Maestro message-type handler** for work log queries. Agents cannot query each other's work logs through the message bus — they must hit the HTTP endpoint directly, which breaks the Maestro messaging contract.

Current structural handlers (no LLM, inline return):
- `directive` → `_handle_directive()`
- `system` → inline ACK
- `BB_WRITE` → `_process_bb_write()`
- `BB_READ` → `_process_bb_read()`

Missing:
- `worklog:query` → should return entries from `_read_work_log()`

## 2. Proposed Message Types

| Message Type | Direction | Body Fields | Response |
|---|---|---|---|
| `worklog:query` | Any agent → target agent | `{agent_id?, limit?}` | `{ok, agent_id, count, entries}` |
| `worklog:subscribe` | Any agent → target agent | `{agent_id?, event_types?}` | `{ok, subscription_id}` *(future)* |

**Phase 1 scope:** `worklog:query` only. Subscribe/push is deferred.

## 3. Design

### 3.1 Message dispatch (in `handle_message`)

Add a new structural handler block between `BB_READ` and the broadcast check:

```python
# Work log query (structural, no LLM)
if msg_type == "worklog:query":
    return await self._handle_worklog_query_msg(message)
```

### 3.2 Handler method

```python
async def _handle_worklog_query_msg(self, message: dict):
    """Handle worklog:query Maestro message type.
    
    Body: {agent_id?: str, limit?: int}
    Returns: {ok, agent_id, count, entries}
    """
    agent_id = message.get("agent_id") or self.agent_id
    limit = min(int(message.get("limit", 20)), 100)
    entries = self._read_work_log(agent_id=agent_id, limit=limit)
    return web.json_response({
        "ok": True,
        "agent_id": agent_id,
        "count": len(entries),
        "entries": entries,
    })
```

### 3.3 Response delivery

For Maestro P2P messages, the response is returned inline as the HTTP response to the sender's POST. This matches the pattern used by `BB_READ` and `directive`.

If the sender needs an async reply via the message bus, that's a different pattern (requires a callback `reply_to` field). **Phase 1 does not include async reply.** The caller POSTs directly to the target agent's `/message` endpoint and gets the worklog JSON back.

## 4. Files Modified

| File | Change |
|---|---|
| `hermes-transport/maestro_transport.py` | Add dispatch block + `_handle_worklog_query_msg()` |
| `transport-shim/maestro_transport.py` | Mirror same changes (shim sync) |

No changes to `_write_work_log()` or `_read_work_log()` — they remain as-is.

## 5. Testing

- Unit: mock a `worklog:query` message, verify dispatch returns entries
- Integration: start transport, POST a `worklog:query` message to `/message`, verify response schema
- Cross-agent: Agent A sends `worklog:query` to Agent B's `/message` endpoint, gets B's work log entries

## 6. Not In Scope (Deferred)

- `worklog:subscribe` — push-based work log streaming
- `worklog:aggregate` — multi-agent log aggregation
- Task log message-type handler (`task:query`) — separate concern
- Search/filter within work log entries (by sender, type, time range)
- File locking for concurrent `_write_work_log` access (currently racy — separate fix)

## 7. Open Questions for Proteus

1. Should `worklog:query` support querying **other agents'** logs, or only the recipient's own? (Current `_read_work_log` accepts any `agent_id` — this enables cross-agent query by default.)
2. Should the response be capped strictly at 100, or do we need pagination (offset + cursor)?
3. Is the shim the only downstream consumer, or are there other transport implementations that need syncing?