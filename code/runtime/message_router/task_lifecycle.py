# task_lifecycle.py — Task Lifecycle (M08)
# Manages explicit task state transitions.
# Filesystem-backed. No transport. No policy decisions.

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
import json
import time
import uuid


class TaskState(Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


VALID_TRANSITIONS = {
    TaskState.PENDING:     {TaskState.CLAIMED, TaskState.CANCELLED},
    TaskState.CLAIMED:     {TaskState.IN_PROGRESS, TaskState.CANCELLED},
    TaskState.IN_PROGRESS: {TaskState.DONE, TaskState.CANCELLED},
    TaskState.DONE:        set(),       # terminal
    TaskState.CANCELLED:   set(),       # terminal
}


@dataclass
class TaskRecord:
    task_id: str
    spec: dict                          # original task specification
    state: TaskState = TaskState.PENDING
    agent_id: Optional[str] = None      # who claimed it
    artifacts: list = field(default_factory=list)  # [{path, hash, size, produced_at}]
    history: list = field(default_factory=list)    # [{from_state, to_state, timestamp, by}]
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at: int = field(default_factory=lambda: int(time.time() * 1000))


class TaskLifecycle:
    """Filesystem-backed task state machine.

    State is stored at ~/.maestro/tasks/{task_id}.json.
    One file per task. No database. No transport dependency.
    """

    def __init__(self, tasks_root: str = "~/.maestro/tasks"):
        self.root = Path(tasks_root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str) -> Path:
        return self.root / f"{task_id}.json"

    def _load(self, task_id: str) -> Optional[dict]:
        p = self._path(task_id)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except Exception:
            return None

    def _save(self, task_id: str, data: dict):
        self._path(task_id).write_text(json.dumps(data, indent=2, ensure_ascii=False))

    # ── Public API ───────────────────────────────────────

    def create_task(self, spec: dict, task_id: str = None) -> str:
        """Create a new task in PENDING state. Returns task_id."""
        tid = task_id or str(uuid.uuid4())
        now = int(time.time() * 1000)
        record = {
            "task_id": tid,
            "spec": spec,
            "state": TaskState.PENDING.value,
            "agent_id": None,
            "artifacts": [],
            "history": [{
                "from_state": None,
                "to_state": TaskState.PENDING.value,
                "timestamp": now,
                "by": "system",
            }],
            "created_at": now,
            "updated_at": now,
        }
        self._save(tid, record)
        return tid

    def claim_task(self, agent_id: str, task_id: str) -> dict:
        """Agent claims a PENDING task. Returns {ok, task_id, state} or {ok: false, reason}."""
        record = self._load(task_id)
        if record is None:
            return {"ok": False, "reason": f"task not found: {task_id}"}
        current = TaskState(record["state"])
        if current != TaskState.PENDING:
            return {"ok": False, "reason": f"task {task_id} is {current.value}, not pending"}
        return self._transition(task_id, record, TaskState.CLAIMED, agent_id=agent_id)

    def start_work(self, agent_id: str, task_id: str) -> dict:
        """Agent begins work on a CLAIMED task."""
        record = self._load(task_id)
        if record is None:
            return {"ok": False, "reason": f"task not found: {task_id}"}
        current = TaskState(record["state"])
        if current != TaskState.CLAIMED:
            return {"ok": False, "reason": f"task {task_id} is {current.value}, not claimed"}
        if record.get("agent_id") != agent_id:
            return {"ok": False, "reason": f"task {task_id} claimed by {record.get('agent_id')}, not {agent_id}"}
        return self._transition(task_id, record, TaskState.IN_PROGRESS)

    def complete_task(self, agent_id: str, task_id: str, artifacts: list = None) -> dict:
        """Mark task DONE with optional artifact manifest."""
        record = self._load(task_id)
        if record is None:
            return {"ok": False, "reason": f"task not found: {task_id}"}
        current = TaskState(record["state"])
        if current != TaskState.IN_PROGRESS:
            return {"ok": False, "reason": f"task {task_id} is {current.value}, not in_progress"}
        if record.get("agent_id") != agent_id:
            return {"ok": False, "reason": f"task {task_id} claimed by {record.get('agent_id')}, not {agent_id}"}
        if artifacts:
            record["artifacts"] = artifacts
        return self._transition(task_id, record, TaskState.DONE)

    def cancel_task(self, task_id: str, by: str = "system") -> dict:
        """Cancel a task from any non-terminal state."""
        record = self._load(task_id)
        if record is None:
            return {"ok": False, "reason": f"task not found: {task_id}"}
        current = TaskState(record["state"])
        if current in (TaskState.DONE, TaskState.CANCELLED):
            return {"ok": False, "reason": f"task {task_id} is already terminal ({current.value})"}
        return self._transition(task_id, record, TaskState.CANCELLED, by=by)

    def cancel_all(self, agent_id: str) -> dict:
        """Cancel all non-terminal tasks for an agent."""
        cancelled = []
        for p in self.root.glob("*.json"):
            try:
                record = json.loads(p.read_text())
                if record.get("agent_id") != agent_id:
                    continue
                state = TaskState(record["state"])
                if state in (TaskState.DONE, TaskState.CANCELLED):
                    continue
                tid = record["task_id"]
                result = self.cancel_task(tid, by="cancel_all")
                if result.get("ok"):
                    cancelled.append(tid)
            except Exception:
                pass
        return {"ok": True, "cancelled": cancelled, "count": len(cancelled)}

    def get_state(self, task_id: str) -> Optional[dict]:
        """Return full task record or None."""
        return self._load(task_id)

    def list_tasks(self, agent_id: str = None, state: str = None) -> list:
        """List tasks, optionally filtered by agent and/or state."""
        results = []
        for p in self.root.glob("*.json"):
            try:
                record = json.loads(p.read_text())
                if agent_id and record.get("agent_id") != agent_id:
                    continue
                if state and record.get("state") != state:
                    continue
                results.append(record)
            except Exception:
                pass
        results.sort(key=lambda r: r.get("updated_at", 0), reverse=True)
        return results

    # ── Internal ─────────────────────────────────────────

    def _transition(self, task_id: str, record: dict, new_state: TaskState,
                    agent_id: str = None, by: str = "system") -> dict:
        current = TaskState(record["state"])
        if new_state not in VALID_TRANSITIONS.get(current, set()):
            return {"ok": False,
                    "reason": f"invalid transition: {current.value} → {new_state.value}"}
        now = int(time.time() * 1000)
        record["state"] = new_state.value
        record["updated_at"] = now
        if agent_id:
            record["agent_id"] = agent_id
        record["history"].append({
            "from_state": current.value,
            "to_state": new_state.value,
            "timestamp": now,
            "by": by,
        })
        self._save(task_id, record)
        return {"ok": True, "task_id": task_id, "state": new_state.value}
