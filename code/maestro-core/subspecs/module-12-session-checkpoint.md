# Module 12: Session Checkpoint — Sub-spec
## Assigned to: Cactus Jack

### Interface Contract
```python
# nucleus/modules/session_checkpoint/interface.py
from dataclasses import dataclass, field

@dataclass
class SessionState:
    agent_id: str
    session_id: str
    active_tasks: list[str]         # task IDs
    context_summary: str            # compressed context
    last_message_id: str | None
    checkpointed_at: int
    version: int

class SessionCheckpoint:
    def save(self, agent_id: str, state: SessionState) -> str: ...  # returns checkpoint_id
    def restore(self, agent_id: str) -> SessionState | None: ...
    def list_checkpoints(self, agent_id: str) -> list[SessionState]: ...
    def prune(self, agent_id: str, keep: int = 5) -> int: ...  # keep last N, returns count pruned
```

### Key Behavior
- **Save:** Write checkpoint to `nucleus/data/checkpoints/{agent_id}/{timestamp}.json`
- **Restore:** Read latest checkpoint for agent, return None if none exist
- **List:** Return all checkpoints for agent, sorted newest first
- **Prune:** Keep only the last N checkpoints, delete older ones
- **Atomic writes:** Write to temp file, rename — no partial writes
- **Create data directory** if it doesn't exist

### Files to Create (absolute paths)
- `/home/andjesse/Projects/Maestro/nucleus/modules/session_checkpoint/__init__.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/session_checkpoint/interface.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/session_checkpoint/checkpoint.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/session_checkpoint/schema.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/session_checkpoint/test_checkpoint.py`

### Dependencies
- Task Lifecycle (M8) — in-flight, being built by Cactus Jack at `/home/andjesse/Projects/Maestro/nucleus/modules/task_lifecycle/`
- If M8 isn't done yet, you can still build M12 — just use the interface contract from the sub-spec at `/home/andjesse/Projects/Maestro/nucleus/subspecs/module-08-task-lifecycle.md` as reference for Task types

### Success Criteria
- Save creates checkpoint file with correct structure
- Restore returns latest checkpoint
- List returns all checkpoints sorted newest first
- Prune keeps only last N, deletes older files
- Atomic writes (no partial files)
- Handles missing data directory gracefully
- Unit tests: save/restore roundtrip, list, prune, missing agent, empty state
