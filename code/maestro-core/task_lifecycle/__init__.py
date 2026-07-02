"""Task Lifecycle — state machine for agent task management.

Exports
-------
* ``TaskState`` — enum of valid task states
* ``TRANSITIONS`` — allowed state transitions
* ``Task`` — dataclass representing a task
* ``TaskLifecycle`` — abstract interface
* ``InMemoryTaskLifecycle`` — in-memory implementation
* ``validate_task`` — schema validator for task entries
"""

from .interface import Task, TaskLifecycle, TaskState, TRANSITIONS
from .lifecycle import InMemoryTaskLifecycle
from .schema import validate_task

__all__ = [
    "InMemoryTaskLifecycle",
    "Task",
    "TaskLifecycle",
    "TaskState",
    "TRANSITIONS",
    "validate_task",
]
