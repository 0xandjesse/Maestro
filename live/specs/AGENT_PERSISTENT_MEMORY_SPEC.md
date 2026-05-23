# Specification: Agent Persistent Memory System
## Version: 1.0
## Date: 2026-05-16
## Author: Proteus (Tech Lead)
## Distributor: Stormtrooper (Implementation)

---

### 1. Purpose
Give every Maestro agent a durable, namespace-isolated persistent memory that survives restarts, session boundaries, and transport reconnects. Memory is queryable by the owning agent and selectively queryable by other officers via a permissions model.

### 2. Architecture

#### 2.1 Storage Layer
- **Backend**: JSON flat files under `~/.maestro/blackboards/`
- **Per-agent namespace**: `memory_{agent_id}.json`
- **Schema**:
  ```json
  {
    "memory.{category}.{key}": {
      "value": <any JSON-serializable value>,
      "updatedBy": "agent_id",
      "timestamp": 1234567890123,
      "ttl": null,
      "access": ["self", "officers"]
    }
  }
  ```

#### 2.2 Key Naming Conventions
- `memory.fact.*` — durable facts about environment, user prefs, project structure
- `memory.recall.*` — session summaries, cross-session context threads
- `memory.task.*` — task-specific state that must survive between tasks
- `memory.agent.*` — metadata about other agents (capabilities, last seen, reliability scores)
- `memory.temp.*` — ephemeral with TTL (auto-expires on read/write)

#### 2.3 Lifecycle
- **Write**: Any BB_WRITE with boardId `memory_{agent_id}` writes to the file
- **Read**: BB_READ with boardId `memory_{agent_id}` reads keys; wildcard prefix search supported
- **TTL Pruning**: On every read/write, keys with `ttl < now` are silently dropped
- **Compaction**: When file exceeds 1000 entries, oldest 200 entries by timestamp are archived to `memory_{agent_id}_archive.json` and removed from active.

#### 2.4 Transport Integration
The `MaestroTransport` class already supports arbitrary board IDs in `_process_bb_write` and `_process_bb_read`. No transport changes needed for basic read/write.

Stormtrooper MUST add:

1. **BB_SEARCH handler** — new message type `BB_SEARCH`
   - `boardId`: target memory board
   - `prefix`: key prefix filter (e.g., `memory.fact.`)
   - `query`: optional fuzzy text search within values
   - `limit`: max results (default 20, max 100)
   - Returns: `{results: [...], total: N}`

2. **BB_DELETE handler** — new message type `BB_DELETE`
   - `boardId`: target memory board
   - `key`: exact key to delete, or `prefix` for bulk delete
   - Returns: `{deleted: N}`

3. **Memory compaction** — background pruning (run on every write)

### 3. Access Control

| Role | Can read | Can write | Can search |
|------|----------|-----------|------------|
| Owner agent | Yes | Yes | Yes |
| Other officers | `access` includes `"officers"` | No | `access` includes `"officers"` |
| Non-officer peers | No | No | No |

Officers: `songbird`, `proteus`, `lexicon`, `hermes`, `mnemosyne`

### 4. P2N Surface Protocol

For Hermes tool integration, Stormtrooper MUST provide a `HermesMemoryTool` class (or equivalent function set) that exposes:

```python
memory_write(agent_id: str, key: str, value: Any, ttl: int = None, access: list = ["self"])
memory_read(agent_id: str, key: str) -> dict
memory_search(agent_id: str, prefix: str = None, query: str = None, limit: int = 20) -> list
memory_delete(agent_id: str, key: str = None, prefix: str = None) -> int
```

These functions read/write from the filesystem directly (not via HTTP) since they run on the same host.

### 5. Officer Cross-Session Recall (wq-4)

Built ON TOP of the persistent memory system.

#### 5.1 Design Pattern
Instead of direct P2P memory queries (which would couple agents too tightly), use the **blackboard as shared recall surface**:

- Each officer periodically (on task finish, or every 30 minutes of activity) writes a `memory.recall.state_snapshot` to their own memory board.
- Snapshot contains: current task, recent decisions, blockers, open questions.
- Any officer can BB_READ another officer's snapshot IF the access field permits.
- The snapshot is written with `access: ["self", "officers"]` by default.

#### 5.2 Query API for Officer Recall
Stormtrooper MUST implement `BB_RECALL` message type:
- `targetAgent`: officer to query
- `queryType`: `snapshot` | `recent_tasks` | `blockers` | `full`
- Returns structured summary, NOT raw memory dump

### 6. Economic Layer (wq-6 — Spec only today)

#### 6.1 Value Proposition
Memories are valuable when they:
- Reduce redundant computation (cached results)
- Capture hard-won context (user corrections, environment quirks)
- Enable coordination (shared state between officers)

#### 6.2 Cost Model (TBD — implement tomorrow)
- **Write cost**: Every memory write consumes "attention budget"
- **Read cost**: Searching another agent's memory costs more than reading own
- **TTL as economic signal**: Short TTL = cheap, Long TTL = expensive
- **Agent credits**: Each agent has a credit balance; expensive ops debit it
- **Memory marketplace**: Agents can offer memories for sale (other agents pay to read)

### 7. Implementation Order for Stormtrooper
1. Implement `BB_SEARCH` handler in `maestro_transport.py`
2. Implement `BB_DELETE` handler in `maestro_transport.py`
3. Implement memory compaction logic
4. Create `hermes_memory.py` module with P2N tool functions
5. Add memory write on task finish (auto-snapshot)
6. Implement `BB_RECALL` for officer cross-session recall
7. Write unit tests

### 8. Acceptance Criteria
- [ ] Agent can write to its own memory and read it back after restart
- [ ] Officer can query another officer's snapshot via BB_RECALL
- [ ] TTL pruning works (expired entries removed)
- [ ] Memory compaction triggers at 1000 entries
- [ ] Access control rejects unauthorized reads
- [ ] P2N tool functions are importable and functional
