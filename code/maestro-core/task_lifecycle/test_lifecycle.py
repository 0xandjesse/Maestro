"""Tests for the Task Lifecycle module.

Covers:
* Task creation
* All valid state transitions
* Invalid transitions raise errors
* CANCEL_ALL directive
* get_active_tasks filtering
* Schema validation
"""

from __future__ import annotations

import pytest

from nucleus.modules.task_lifecycle import (
    InMemoryTaskLifecycle,
    Task,
    TaskState,
    TRANSITIONS,
    validate_task,
)


# ── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def lifecycle():
    """Return a fresh InMemoryTaskLifecycle."""
    return InMemoryTaskLifecycle()


@pytest.fixture
def pending_task(lifecycle):
    """Return a lifecycle with one PENDING task."""
    task = lifecycle.create_task("agent-1", "Test task")
    return lifecycle, task


# ── task creation ──────────────────────────────────────────────────────


class TestTaskCreation:
    def test_create_task(self, lifecycle):
        task = lifecycle.create_task("agent-1", "Do the thing")
        assert isinstance(task, Task)
        assert task.agent_id == "agent-1"
        assert task.description == "Do the thing"
        assert task.state == TaskState.PENDING
        assert task.created_at > 0
        assert task.started_at is None
        assert task.completed_at is None
        assert task.result is None
        assert task.artifacts == []
        assert task.parent_task_id is None
        assert len(task.task_id) == 16

    def test_create_task_unique_ids(self, lifecycle):
        t1 = lifecycle.create_task("agent-1", "Task 1")
        t2 = lifecycle.create_task("agent-1", "Task 2")
        assert t1.task_id != t2.task_id

    def test_create_task_with_parent(self, lifecycle):
        parent = lifecycle.create_task("agent-1", "Parent")
        child = lifecycle.create_task("agent-1", "Child", parent_task_id=parent.task_id)
        assert child.parent_task_id == parent.task_id

    def test_create_task_empty_agent_id(self, lifecycle):
        with pytest.raises(ValueError, match="agent_id"):
            lifecycle.create_task("", "desc")

    def test_create_task_empty_description(self, lifecycle):
        with pytest.raises(ValueError, match="description"):
            lifecycle.create_task("agent-1", "")

    def test_get_task(self, lifecycle):
        task = lifecycle.create_task("agent-1", "Find me")
        found = lifecycle.get_task(task.task_id)
        assert found is not None
        assert found.task_id == task.task_id

    def test_get_task_missing(self, lifecycle):
        assert lifecycle.get_task("nonexistent") is None


# ── valid transitions ──────────────────────────────────────────────────


class TestValidTransitions:
    def test_pending_to_claimed(self, pending_task):
        lifecycle, task = pending_task
        updated = lifecycle.transition(task.task_id, TaskState.CLAIMED)
        assert updated.state == TaskState.CLAIMED
        assert updated.started_at is not None

    def test_pending_to_cancelled(self, pending_task):
        lifecycle, task = pending_task
        updated = lifecycle.transition(task.task_id, TaskState.CANCELLED)
        assert updated.state == TaskState.CANCELLED
        assert updated.completed_at is not None

    def test_claimed_to_in_progress(self, pending_task):
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CLAIMED)
        updated = lifecycle.transition(task.task_id, TaskState.IN_PROGRESS)
        assert updated.state == TaskState.IN_PROGRESS

    def test_claimed_to_cancelled(self, pending_task):
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CLAIMED)
        updated = lifecycle.transition(task.task_id, TaskState.CANCELLED)
        assert updated.state == TaskState.CANCELLED
        assert updated.completed_at is not None

    def test_in_progress_to_done(self, pending_task):
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CLAIMED)
        lifecycle.transition(task.task_id, TaskState.IN_PROGRESS)
        updated = lifecycle.transition(task.task_id, TaskState.DONE)
        assert updated.state == TaskState.DONE
        assert updated.completed_at is not None

    def test_in_progress_to_blocked(self, pending_task):
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CLAIMED)
        lifecycle.transition(task.task_id, TaskState.IN_PROGRESS)
        updated = lifecycle.transition(task.task_id, TaskState.BLOCKED)
        assert updated.state == TaskState.BLOCKED

    def test_in_progress_to_cancelled(self, pending_task):
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CLAIMED)
        lifecycle.transition(task.task_id, TaskState.IN_PROGRESS)
        updated = lifecycle.transition(task.task_id, TaskState.CANCELLED)
        assert updated.state == TaskState.CANCELLED
        assert updated.completed_at is not None

    def test_blocked_to_in_progress(self, pending_task):
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CLAIMED)
        lifecycle.transition(task.task_id, TaskState.IN_PROGRESS)
        lifecycle.transition(task.task_id, TaskState.BLOCKED)
        updated = lifecycle.transition(task.task_id, TaskState.IN_PROGRESS)
        assert updated.state == TaskState.IN_PROGRESS

    def test_blocked_to_cancelled(self, pending_task):
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CLAIMED)
        lifecycle.transition(task.task_id, TaskState.IN_PROGRESS)
        lifecycle.transition(task.task_id, TaskState.BLOCKED)
        updated = lifecycle.transition(task.task_id, TaskState.CANCELLED)
        assert updated.state == TaskState.CANCELLED
        assert updated.completed_at is not None

    def test_full_happy_path(self, pending_task):
        """PENDING -> CLAIMED -> IN_PROGRESS -> DONE."""
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CLAIMED)
        lifecycle.transition(task.task_id, TaskState.IN_PROGRESS)
        updated = lifecycle.transition(task.task_id, TaskState.DONE)
        assert updated.state == TaskState.DONE
        assert updated.started_at is not None
        assert updated.completed_at is not None
        assert updated.completed_at >= updated.started_at


# ── invalid transitions ────────────────────────────────────────────────


class TestInvalidTransitions:
    def test_done_cannot_transition(self, pending_task):
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CLAIMED)
        lifecycle.transition(task.task_id, TaskState.IN_PROGRESS)
        lifecycle.transition(task.task_id, TaskState.DONE)

        for target in TaskState:
            with pytest.raises(ValueError, match="Invalid transition"):
                lifecycle.transition(task.task_id, target)

    def test_cancelled_cannot_transition(self, pending_task):
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CANCELLED)

        for target in TaskState:
            with pytest.raises(ValueError, match="Invalid transition"):
                lifecycle.transition(task.task_id, target)

    def test_pending_to_done_invalid(self, pending_task):
        lifecycle, task = pending_task
        with pytest.raises(ValueError, match="Invalid transition"):
            lifecycle.transition(task.task_id, TaskState.DONE)

    def test_pending_to_blocked_invalid(self, pending_task):
        lifecycle, task = pending_task
        with pytest.raises(ValueError, match="Invalid transition"):
            lifecycle.transition(task.task_id, TaskState.BLOCKED)

    def test_pending_to_in_progress_invalid(self, pending_task):
        lifecycle, task = pending_task
        with pytest.raises(ValueError, match="Invalid transition"):
            lifecycle.transition(task.task_id, TaskState.IN_PROGRESS)

    def test_claimed_to_done_invalid(self, pending_task):
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CLAIMED)
        with pytest.raises(ValueError, match="Invalid transition"):
            lifecycle.transition(task.task_id, TaskState.DONE)

    def test_claimed_to_blocked_invalid(self, pending_task):
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CLAIMED)
        with pytest.raises(ValueError, match="Invalid transition"):
            lifecycle.transition(task.task_id, TaskState.BLOCKED)

    def test_blocked_to_done_invalid(self, pending_task):
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CLAIMED)
        lifecycle.transition(task.task_id, TaskState.IN_PROGRESS)
        lifecycle.transition(task.task_id, TaskState.BLOCKED)
        with pytest.raises(ValueError, match="Invalid transition"):
            lifecycle.transition(task.task_id, TaskState.DONE)

    def test_transition_nonexistent_task(self, lifecycle):
        with pytest.raises(ValueError, match="not found"):
            lifecycle.transition("nonexistent", TaskState.CLAIMED)


# ── cancel_all ─────────────────────────────────────────────────────────


class TestCancelAll:
    def test_cancel_all_single(self, pending_task):
        lifecycle, task = pending_task
        cancelled = lifecycle.cancel_all("agent-1")
        assert len(cancelled) == 1
        assert cancelled[0].task_id == task.task_id
        assert cancelled[0].state == TaskState.CANCELLED
        assert cancelled[0].completed_at is not None

    def test_cancel_all_multiple(self, lifecycle):
        t1 = lifecycle.create_task("agent-1", "Task 1")
        t2 = lifecycle.create_task("agent-1", "Task 2")
        t3 = lifecycle.create_task("agent-1", "Task 3")

        # Move one to CLAIMED, one to IN_PROGRESS, leave one PENDING
        lifecycle.transition(t1.task_id, TaskState.CLAIMED)
        lifecycle.transition(t2.task_id, TaskState.CLAIMED)
        lifecycle.transition(t2.task_id, TaskState.IN_PROGRESS)

        cancelled = lifecycle.cancel_all("agent-1")
        assert len(cancelled) == 3

        for t in cancelled:
            assert t.state == TaskState.CANCELLED
            assert t.completed_at is not None

    def test_cancel_all_skips_done(self, lifecycle):
        t1 = lifecycle.create_task("agent-1", "Task 1")
        t2 = lifecycle.create_task("agent-1", "Task 2")

        # Complete t1
        lifecycle.transition(t1.task_id, TaskState.CLAIMED)
        lifecycle.transition(t1.task_id, TaskState.IN_PROGRESS)
        lifecycle.transition(t1.task_id, TaskState.DONE)

        cancelled = lifecycle.cancel_all("agent-1")
        assert len(cancelled) == 1
        assert cancelled[0].task_id == t2.task_id

        # t1 should still be DONE
        assert lifecycle.get_task(t1.task_id).state == TaskState.DONE

    def test_cancel_all_skips_cancelled(self, lifecycle):
        t1 = lifecycle.create_task("agent-1", "Task 1")
        t2 = lifecycle.create_task("agent-1", "Task 2")

        lifecycle.transition(t1.task_id, TaskState.CANCELLED)

        cancelled = lifecycle.cancel_all("agent-1")
        assert len(cancelled) == 1
        assert cancelled[0].task_id == t2.task_id

    def test_cancel_all_other_agent_unaffected(self, lifecycle):
        t1 = lifecycle.create_task("agent-1", "Task 1")
        t2 = lifecycle.create_task("agent-2", "Task 2")

        cancelled = lifecycle.cancel_all("agent-1")
        assert len(cancelled) == 1
        assert cancelled[0].task_id == t1.task_id

        # agent-2's task should still be PENDING
        assert lifecycle.get_task(t2.task_id).state == TaskState.PENDING

    def test_cancel_all_no_active_tasks(self, lifecycle):
        t1 = lifecycle.create_task("agent-1", "Task 1")
        lifecycle.transition(t1.task_id, TaskState.CLAIMED)
        lifecycle.transition(t1.task_id, TaskState.IN_PROGRESS)
        lifecycle.transition(t1.task_id, TaskState.DONE)

        cancelled = lifecycle.cancel_all("agent-1")
        assert cancelled == []

    def test_cancel_all_unknown_agent(self, lifecycle):
        cancelled = lifecycle.cancel_all("nobody")
        assert cancelled == []


# ── get_active_tasks ───────────────────────────────────────────────────


class TestGetActiveTasks:
    def test_get_active_tasks_pending(self, lifecycle):
        t1 = lifecycle.create_task("agent-1", "Task 1")
        active = lifecycle.get_active_tasks("agent-1")
        assert len(active) == 1
        assert active[0].task_id == t1.task_id

    def test_get_active_tasks_mixed_states(self, lifecycle):
        t1 = lifecycle.create_task("agent-1", "Task 1")  # PENDING
        t2 = lifecycle.create_task("agent-1", "Task 2")  # PENDING
        t3 = lifecycle.create_task("agent-1", "Task 3")  # PENDING

        lifecycle.transition(t1.task_id, TaskState.CLAIMED)
        lifecycle.transition(t2.task_id, TaskState.CLAIMED)
        lifecycle.transition(t2.task_id, TaskState.IN_PROGRESS)
        lifecycle.transition(t2.task_id, TaskState.DONE)

        active = lifecycle.get_active_tasks("agent-1")
        assert len(active) == 2  # t1 (CLAIMED) and t3 (PENDING)
        active_ids = {t.task_id for t in active}
        assert t1.task_id in active_ids
        assert t3.task_id in active_ids
        assert t2.task_id not in active_ids  # DONE

    def test_get_active_tasks_blocked(self, lifecycle):
        t1 = lifecycle.create_task("agent-1", "Task 1")
        lifecycle.transition(t1.task_id, TaskState.CLAIMED)
        lifecycle.transition(t1.task_id, TaskState.IN_PROGRESS)
        lifecycle.transition(t1.task_id, TaskState.BLOCKED)

        active = lifecycle.get_active_tasks("agent-1")
        assert len(active) == 1  # BLOCKED is active

    def test_get_active_tasks_all_done(self, lifecycle):
        t1 = lifecycle.create_task("agent-1", "Task 1")
        lifecycle.transition(t1.task_id, TaskState.CLAIMED)
        lifecycle.transition(t1.task_id, TaskState.IN_PROGRESS)
        lifecycle.transition(t1.task_id, TaskState.DONE)

        active = lifecycle.get_active_tasks("agent-1")
        assert active == []

    def test_get_active_tasks_other_agent(self, lifecycle):
        lifecycle.create_task("agent-1", "Task 1")
        active = lifecycle.get_active_tasks("agent-2")
        assert active == []


# ── TRANSITIONS table correctness ──────────────────────────────────────


class TestTransitionsTable:
    def test_all_states_have_entries(self):
        for state in TaskState:
            assert state in TRANSITIONS, f"{state} missing from TRANSITIONS"

    def test_terminal_states_have_no_exits(self):
        assert TRANSITIONS[TaskState.DONE] == []
        assert TRANSITIONS[TaskState.CANCELLED] == []

    def test_transitions_are_taskstate_instances(self):
        for state, targets in TRANSITIONS.items():
            assert isinstance(state, TaskState)
            for target in targets:
                assert isinstance(target, TaskState)


# ── schema validation ──────────────────────────────────────────────────


class TestSchemaValidation:
    def test_valid_task(self):
        errors = validate_task({
            "task_id": "abc123def456",
            "agent_id": "agent-1",
            "description": "Do something",
            "state": "pending",
            "created_at": 1000,
        })
        assert errors == []

    def test_valid_task_all_fields(self):
        errors = validate_task({
            "task_id": "abc123def456",
            "agent_id": "agent-1",
            "description": "Do something",
            "state": "done",
            "created_at": 1000,
            "started_at": 1100,
            "completed_at": 1200,
            "result": "All good",
            "artifacts": ["/tmp/out.txt"],
            "parent_task_id": "parent123",
        })
        assert errors == []

    def test_missing_required_fields(self):
        errors = validate_task({"task_id": "abc"})
        assert len(errors) > 0

    def test_invalid_state(self):
        errors = validate_task({
            "task_id": "abc",
            "agent_id": "a",
            "description": "d",
            "state": "flying",
            "created_at": 1,
        })
        assert any("flying" in e for e in errors)

    def test_not_a_dict(self):
        errors = validate_task(["not", "a", "dict"])
        assert any("dict" in e for e in errors)

    def test_bad_artifacts(self):
        errors = validate_task({
            "task_id": "abc",
            "agent_id": "a",
            "description": "d",
            "state": "pending",
            "created_at": 1,
            "artifacts": "not-a-list",
        })
        assert any("artifacts" in e for e in errors)

    def test_bad_started_at(self):
        errors = validate_task({
            "task_id": "abc",
            "agent_id": "a",
            "description": "d",
            "state": "pending",
            "created_at": 1,
            "started_at": "yesterday",
        })
        assert any("started_at" in e for e in errors)


# ── edge cases ─────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_multiple_agents_isolation(self, lifecycle):
        t1 = lifecycle.create_task("agent-1", "A1 task")
        t2 = lifecycle.create_task("agent-2", "A2 task")

        lifecycle.transition(t1.task_id, TaskState.CLAIMED)
        lifecycle.transition(t1.task_id, TaskState.IN_PROGRESS)
        lifecycle.transition(t1.task_id, TaskState.DONE)

        # agent-2's task should still be PENDING
        assert lifecycle.get_task(t2.task_id).state == TaskState.PENDING

    def test_started_at_set_once(self, pending_task):
        """started_at should be set on first transition out of PENDING and not change."""
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CLAIMED)
        started = lifecycle.get_task(task.task_id).started_at
        assert started is not None

        lifecycle.transition(task.task_id, TaskState.IN_PROGRESS)
        assert lifecycle.get_task(task.task_id).started_at == started

    def test_completed_at_set_on_done(self, pending_task):
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CLAIMED)
        lifecycle.transition(task.task_id, TaskState.IN_PROGRESS)
        lifecycle.transition(task.task_id, TaskState.DONE)
        assert lifecycle.get_task(task.task_id).completed_at is not None

    def test_completed_at_set_on_cancelled(self, pending_task):
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CANCELLED)
        assert lifecycle.get_task(task.task_id).completed_at is not None

    def test_completed_at_none_for_active(self, pending_task):
        lifecycle, task = pending_task
        lifecycle.transition(task.task_id, TaskState.CLAIMED)
        lifecycle.transition(task.task_id, TaskState.IN_PROGRESS)
        lifecycle.transition(task.task_id, TaskState.BLOCKED)
        assert lifecycle.get_task(task.task_id).completed_at is None

    def test_task_count(self, lifecycle):
        assert lifecycle._task_count() == 0
        lifecycle.create_task("agent-1", "T1")
        assert lifecycle._task_count() == 1
        lifecycle.create_task("agent-1", "T2")
        assert lifecycle._task_count() == 2
