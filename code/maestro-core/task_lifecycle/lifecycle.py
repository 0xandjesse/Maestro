"""Task Lifecycle — in-memory state machine implementation.

Implements the TaskLifecycle interface with:
* Validated state transitions
* CANCEL_ALL directive support
* In-memory store (no file I/O)
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from .interface import Task, TaskLifecycle, TaskState, TRANSITIONS


class InMemoryTaskLifecycle(TaskLifecycle):
    """In-memory task lifecycle manager.

    Tasks are stored in a dict keyed by task_id.  All state transitions
    are validated against the TRANSITIONS table.  Terminal states
    (DONE, CANCELLED) cannot be transitioned out of.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    # ── public API ─────────────────────────────────────────────────────

    def create_task(
        self,
        agent_id: str,
        description: str,
        parent_task_id: str | None = None,
    ) -> Task:
        """Create a new task in PENDING state."""
        if not agent_id or not isinstance(agent_id, str):
            raise ValueError("agent_id must be a non-empty string")
        if not description or not isinstance(description, str):
            raise ValueError("description must be a non-empty string")

        task_id = uuid.uuid4().hex[:16]
        now_ms = int(time.time() * 1000)

        task = Task(
            task_id=task_id,
            agent_id=agent_id,
            description=description,
            state=TaskState.PENDING,
            created_at=now_ms,
            parent_task_id=parent_task_id,
        )

        self._tasks[task_id] = task
        return task

    def transition(self, task_id: str, new_state: TaskState) -> Task:
        """Move *task_id* to *new_state* if the transition is valid."""
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task {task_id!r} not found")

        allowed = TRANSITIONS.get(task.state, [])
        if new_state not in allowed:
            raise ValueError(
                f"Invalid transition: {task.state.value} -> {new_state.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        now_ms = int(time.time() * 1000)

        # Set started_at on first transition out of PENDING
        if task.state == TaskState.PENDING and task.started_at is None:
            task.started_at = now_ms

        # Set completed_at when entering a terminal state
        if new_state in (TaskState.DONE, TaskState.CANCELLED):
            task.completed_at = now_ms

        task.state = new_state
        return task

    def cancel_all(self, agent_id: str) -> list[Task]:
        """Cancel all active (non-terminal) tasks for *agent_id*."""
        cancelled: list[Task] = []
        now_ms = int(time.time() * 1000)

        for task in self._tasks.values():
            if task.agent_id != agent_id:
                continue
            if task.state in (TaskState.DONE, TaskState.CANCELLED):
                continue

            task.state = TaskState.CANCELLED
            task.completed_at = now_ms
            cancelled.append(task)

        return cancelled

    def get_active_tasks(self, agent_id: str) -> list[Task]:
        """Return all active (non-terminal) tasks for *agent_id*."""
        return [
            t
            for t in self._tasks.values()
            if t.agent_id == agent_id
            and t.state not in (TaskState.DONE, TaskState.CANCELLED)
        ]

    def get_task(self, task_id: str) -> Task | None:
        """Return the task with *task_id*, or None if not found."""
        return self._tasks.get(task_id)

    # ── helpers for testing ────────────────────────────────────────────

    def _task_count(self) -> int:
        """Return the total number of tasks in the store."""
        return len(self._tasks)

    def _to_dict(self, task_id: str) -> dict[str, Any] | None:
        """Serialize a task to a dict for schema validation."""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        return {
            "task_id": task.task_id,
            "agent_id": task.agent_id,
            "description": task.description,
            "state": task.state.value,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "result": task.result,
            "artifacts": task.artifacts,
            "parent_task_id": task.parent_task_id,
        }
