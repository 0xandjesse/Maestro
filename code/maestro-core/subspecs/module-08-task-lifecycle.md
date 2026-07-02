# Module 8: Task Lifecycle — Sub-spec
## Assigned to: Cactus Jack

### Interface Contract
```python
# nucleus/modules/task_lifecycle/interface.py
from enum import Enum
from dataclasses import dataclass, field

class TaskState(Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"

TRANSITIONS = {
    TaskState.PENDING:     [TaskState.CLAIMED, TaskState.CANCELLED],
    TaskState.CLAIMED:     [TaskState.IN_PROGRESS, TaskState.CANCELLED],
    TaskState.IN_PROGRESS: [TaskState.DONE, TaskState.BLOCKED, TaskState.CANCELLED],
    TaskState.BLOCKED:     [TaskState.IN_PROGRESS, TaskState.CANCELLED],
    TaskState.DONE:        [],
    TaskState.CANCELLED:   [],
}

@dataclass
class Task:
    task_id: str
    agent_id: str
    description: str
    state: TaskState
    created_at: int
    started_at: int | None = None
    completed_at: int | None = None
    result: str | None = None
    artifacts: list[str] = field(default_factory=list)
    parent_task_id: str | None = None

class TaskLifecycle:
    def create_task(self, agent_id: str, description: str, parent_task_id: str | None = None) -> Task: ...
    def transition(self, task_id: str, new_state: TaskState) -> Task: ...
    def cancel_all(self, agent_id: str) -> list[Task]: ...
    def get_active_tasks(self, agent_id: str) -> list[Task]: ...
    def get_task(self, task_id: str) -> Task | None: ...
```

### Key Behavior
- State machine with validated transitions
- CANCEL_ALL directive support
- In-memory store (no file I/O needed for this module)

### Files to Create (absolute paths)
- `/home/andjesse/Projects/Maestro/nucleus/modules/task_lifecycle/__init__.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/task_lifecycle/interface.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/task_lifecycle/lifecycle.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/task_lifecycle/schema.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/task_lifecycle/test_lifecycle.py`

### Dependencies
None — fully independent.

### Success Criteria
- All valid transitions work
- Invalid transitions raise errors
- CANCEL_ALL cancels all active tasks for an agent
- Unit tests: all transitions, invalid transitions, cancel_all, get_active
