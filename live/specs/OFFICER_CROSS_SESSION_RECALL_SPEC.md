# Specification: Officer Cross-Session Recall System
## Version: 1.0
## Date: 2026-05-16
## Author: Proteus (Tech Lead)
## Distributor: Stormtrooper (Implementation)

---

### 1. Purpose
Enable Songbird, Proteus, Lexicon, Hermes, and Mnemosyne to query each other's persistent memory state without direct P2P coupling. The blackboard serves as the shared recall surface — each officer writes, any officer reads (with permissions).

### 2. Officers Registry
```python
OFFICERS = {"songbird", "proteus", "lexicon", "hermes", "mnemosyne"}
```

### 3. Memory Snapshot Format

Each officer, upon task completion or every 30 minutes of active runtime, MUST write a snapshot to their own memory board:

```json
{
  "memory.recall.snapshot.latest": {
    "value": {
      "agent_id": "lexicon",
      "timestamp": 1778889180852,
      "iso_time": "2026-05-16T00:20:00Z",
      "current_task": "Monitoring infrastructure health",
      "recent_decisions": [
        {"decision": "Approved firewall rule update", "rationale": "Security patch required by CVE-2026-1234", "timestamp": 1778889000000}
      ],
      "blockers": [],
      "open_questions": [
        {"question": "Should we migrate backups to S3?", "context": "Disk usage at 78% on backup server"}
      ],
      "health_status": "green",
      "queue_depth": 0,
      "last_brief_to_songbird": 1778888000000
    },
    "updatedBy": "lexicon",
    "timestamp": 1778889180852,
    "ttl": 86400,
    "access": ["self", "officers"]
  }
}
```

### 4. BB_RECALL Message Type

Stormtrooper MUST implement a new structural message type `BB_RECALL` (no LLM processing):

**Request schema:**
```json
{
  "id": "unique-msg-id",
  "type": "BB_RECALL",
  "sender": {"agentId": "proteus"},
  "targetAgent": "lexicon",
  "queryType": "snapshot",
  "limit": 10
}
```

**queryType values:**
- `snapshot` — return the latest `memory.recall.snapshot.latest` for targetAgent
- `recent_tasks` — return recent `memory.task.*` entries for targetAgent
- `blockers` — return any `memory.recall.*` entries where `value.blockers` is non-empty
- `full` — return all memory entries targetAgent has shared with officers (respecting access)
- `search` — requires `query` field; fuzzy search across all accessible memory entries

**Response:** System reply routed back to sender:
```json
{
  "id": "reply-id",
  "type": "system",
  "sender": {"agentId": "lexicon"},
  "recipient": "proteus",
  "content": "[lexicon] BB_RECALL OK: snapshot for lexicon — current_task: Monitoring infrastructure health, blockers: [], health: green"
}
```

### 5. Access Control (Officer-Specific)

| Target | queryType | Requester | Allowed? |
|--------|-----------|-----------|----------|
| Any officer | snapshot, recent_tasks, blockers | Any officer | YES if access includes "officers" |
| Any officer | full, search | Any officer | YES if access includes "officers" |
| Any officer | Any | Non-officer peer | NO |
| Any officer | Any | self | YES |

The transport's `_process_bb_recall` handler MUST check `sender.agentId` against `OFFICERS` and deny with a 403-equivalent system reply if unauthorized.

### 6. Auto-Snapshot Trigger

The transport MUST auto-write a snapshot on two conditions:
1. When a task:finish message is processed and the task duration exceeded 60 seconds
2. Every 30 minutes of wall-clock time since last snapshot (heartbeat)

The snapshot format is fixed — agents MUST NOT customize the schema, only populate the values.

### 7. Implementation for Stormtrooper

1. Add `OFFICERS` constant to `maestro_transport.py`
2. Add `_process_bb_recall` method in `MaestroTransport`
3. Add auto-snapshot logic in `handle_message` (after task:finish) and in a background task (30m heartbeat)
4. Add `_write_officer_snapshot` helper method
5. Unit tests for access control (officer vs non-officer), query types, and auto-snapshot trigger

### 8. Dependent on
- Agent Persistent Memory system (wq-3) — BB_SEARCH and memory storage must work first

### 9. Acceptance Criteria
- [ ] Proteus can BB_RECALL snapshot from Lexicon and get structured response
- [ ] Non-officer agent attempting BB_RECALL gets access denied
- [ ] Auto-snapshot written after long task completion
- [ ] Heartbeat snapshot written every 30m
- [ ] queryType=blockers returns only officers with active blockers
- [ ] queryType=search supports fuzzy text matching
