"""Schema validation for task entries.

Every task passes through these validators before being stored.
Malformed entries are rejected.
"""

from __future__ import annotations

from typing import Any

from .interface import TaskState


# ── per-field constraints ──────────────────────────────────────────────


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and value >= 0


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


# ── task validation ─────────────────────────────────────────────────────


def validate_task(task: dict[str, Any]) -> list[str]:
    """Validate a single task entry.

    Returns a list of error messages (empty list = valid).
    """
    errors: list[str] = []

    if not isinstance(task, dict):
        return ["task entry is not a dict"]

    # task_id — required
    if not _is_nonempty_str(task.get("task_id")):
        errors.append("task_id must be a non-empty string")

    # agent_id — required
    if not _is_nonempty_str(task.get("agent_id")):
        errors.append("agent_id must be a non-empty string")

    # description — required
    if not _is_nonempty_str(task.get("description")):
        errors.append("description must be a non-empty string")

    # state — required, must be a valid TaskState value
    state_raw = task.get("state")
    if not _is_nonempty_str(state_raw):
        errors.append("state must be a non-empty string")
    else:
        valid_states = {s.value for s in TaskState}
        if state_raw not in valid_states:
            errors.append(
                f"state {state_raw!r} is not a valid TaskState "
                f"(valid: {sorted(valid_states)})"
            )

    # created_at — required
    if not _is_positive_int(task.get("created_at")):
        errors.append("created_at must be a non-negative integer")

    # started_at — optional, but if present must be int
    started = task.get("started_at")
    if started is not None and not isinstance(started, int):
        errors.append("started_at must be an integer or null")

    # completed_at — optional, but if present must be int
    completed = task.get("completed_at")
    if completed is not None and not isinstance(completed, int):
        errors.append("completed_at must be an integer or null")

    # result — optional, but if present must be str
    result = task.get("result")
    if result is not None and not isinstance(result, str):
        errors.append("result must be a string or null")

    # artifacts — optional, but if present must be list[str]
    artifacts = task.get("artifacts")
    if artifacts is not None and not _is_str_list(artifacts):
        errors.append("artifacts must be a list of strings")

    # parent_task_id — optional, but if present must be str
    parent = task.get("parent_task_id")
    if parent is not None and not isinstance(parent, str):
        errors.append("parent_task_id must be a string or null")

    return errors
