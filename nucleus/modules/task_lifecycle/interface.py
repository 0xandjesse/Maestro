"""Task Lifecycle — Interface Contract.

Defines TaskState, TRANSITIONS, Task, and the TaskLifecycle
abstract base class that all implementations must satisfy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class TaskState(Enum):
    """Valid states for a task in the lifecycle state machine."""

    PENDING = "pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


TRANSITIONS: dict[TaskState, list[TaskState]] = {
    TaskState.PENDING:     [TaskState.CLAIMED, TaskState.CANCELLED],
    TaskState.CLAIMED:     [TaskState.IN_PROGRESS, TaskState.CANCELLED],
    TaskState.IN_PROGRESS: [TaskState.DONE, TaskState.BLOCKED, TaskState.CANCELLED],
    TaskState.BLOCKED:     [TaskState.IN_PROGRESS, TaskState.CANCELLED],
    TaskState.DONE:        [],
    TaskState.CANCELLED:   [],
}


@dataclass
class Task:
    """A unit of work tracked through the lifecycle state machine.

    Attributes
    ----------
    task_id : str
        Unique identifier for this task.
    agent_id : str
        The agent this task is assigned to.
    description : str
        Human-readable description of the work.
    state : TaskState
        Current state in the lifecycle.
    created_at : int
        Unix timestamp (milliseconds) when the task was created.
    started_at : int | None
        Unix timestamp (milliseconds) when work began, or None.
    completed_at : int | None
        Unix timestamp (milliseconds) when the task finished, or None.
    result : str | None
        Outcome summary, or None if not yet completed.
    artifacts : list[str]
        Paths or identifiers of artifacts produced by this task.
    parent_task_id : str | None
        The task that spawned this one, or None for top-level tasks.
    """

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


class TaskLifecycle(ABC):
    """Abstract interface for task lifecycle management.

    Implementations must provide a state machine with validated
    transitions, task creation, cancellation, and query methods.
    """

    @abstractmethod
    def create_task(
        self,
        agent_id: str,
        description: str,
        parent_task_id: str | None = None,
    ) -> Task:
        """Create a new task in PENDING state.

        Parameters
        ----------
        agent_id : str
            The agent this task is assigned to.
        description : str
            Human-readable description of the work.
        parent_task_id : str | None
            Optional parent task that spawned this one.

        Returns
        -------
        Task
            The newly created task.
        """
        ...

    @abstractmethod
    def transition(self, task_id: str, new_state: TaskState) -> Task:
        """Move *task_id* to *new_state* if the transition is valid.

        Parameters
        ----------
        task_id : str
            The task to transition.
        new_state : TaskState
            The target state.

        Returns
        -------
        Task
            The updated task.

        Raises
        ------
        ValueError
            If the task does not exist or the transition is invalid.
        """
        ...

    @abstractmethod
    def cancel_all(self, agent_id: str) -> list[Task]:
        """Cancel all active (non-terminal) tasks for *agent_id*.

        Active means any state other than DONE or CANCELLED.

        Parameters
        ----------
        agent_id : str
            The agent whose tasks should be cancelled.

        Returns
        -------
        list[Task]
            The tasks that were cancelled.
        """
        ...

    @abstractmethod
    def get_active_tasks(self, agent_id: str) -> list[Task]:
        """Return all active (non-terminal) tasks for *agent_id*.

        Parameters
        ----------
        agent_id : str
            The agent to query.

        Returns
        -------
        list[Task]
            Tasks in PENDING, CLAIMED, IN_PROGRESS, or BLOCKED state.
        """
        ...

    @abstractmethod
    def get_task(self, task_id: str) -> Task | None:
        """Return the task with *task_id*, or None if not found.

        Parameters
        ----------
        task_id : str
            The task identifier.

        Returns
        -------
        Task | None
            The matching task, or None.
        """
        ...
