# test_task_lifecycle.py — 15+ tests for Task Lifecycle (M08)

import json
import os
import sys
import tempfile
from pathlib import Path

# Add the runtime directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "code" / "runtime" / "message_router"))

from task_lifecycle import TaskLifecycle, TaskState


# ── Fixture ─────────────────────────────────────────────

def make_tl():
    """Create a TaskLifecycle with a temp directory."""
    tmp = tempfile.mkdtemp()
    return TaskLifecycle(tasks_root=tmp), tmp


# ── create_task tests ───────────────────────────────────

def test_create_task_returns_id():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    assert tid is not None
    assert len(tid) > 0


def test_create_task_state_is_pending():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    state = tl.get_state(tid)
    assert state["state"] == TaskState.PENDING.value


def test_create_task_with_custom_id():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"}, task_id="my-task-1")
    assert tid == "my-task-1"
    state = tl.get_state("my-task-1")
    assert state is not None


# ── claim_task tests ────────────────────────────────────

def test_claim_task_ok():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    result = tl.claim_task("alice", tid)
    assert result["ok"] is True
    assert result["state"] == TaskState.CLAIMED.value


def test_claim_task_not_found():
    tl, tmp = make_tl()
    result = tl.claim_task("alice", "nonexistent")
    assert result["ok"] is False
    assert "not found" in result["reason"]


def test_claim_task_already_claimed():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    tl.claim_task("alice", tid)
    result = tl.claim_task("bob", tid)
    assert result["ok"] is False
    assert "not pending" in result["reason"]


# ── start_work tests ────────────────────────────────────

def test_start_work_ok():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    tl.claim_task("alice", tid)
    result = tl.start_work("alice", tid)
    assert result["ok"] is True
    assert result["state"] == TaskState.IN_PROGRESS.value


def test_start_work_wrong_agent():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    tl.claim_task("alice", tid)
    result = tl.start_work("bob", tid)
    assert result["ok"] is False
    assert "claimed by alice" in result["reason"]


def test_start_work_not_claimed():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    result = tl.start_work("alice", tid)
    assert result["ok"] is False
    assert "not claimed" in result["reason"]


# ── complete_task tests ─────────────────────────────────

def test_complete_task_ok():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    tl.claim_task("alice", tid)
    tl.start_work("alice", tid)
    result = tl.complete_task("alice", tid)
    assert result["ok"] is True
    assert result["state"] == TaskState.DONE.value


def test_complete_task_with_artifacts():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    tl.claim_task("alice", tid)
    tl.start_work("alice", tid)
    artifacts = [{"path": "/tmp/out.json", "hash": "abc123"}]
    result = tl.complete_task("alice", tid, artifacts=artifacts)
    assert result["ok"] is True
    state = tl.get_state(tid)
    assert state["artifacts"] == artifacts


def test_complete_task_not_in_progress():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    result = tl.complete_task("alice", tid)
    assert result["ok"] is False
    assert "not in_progress" in result["reason"]


# ── cancel_task tests ───────────────────────────────────

def test_cancel_task_from_pending():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    result = tl.cancel_task(tid)
    assert result["ok"] is True
    assert result["state"] == TaskState.CANCELLED.value


def test_cancel_task_from_claimed():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    tl.claim_task("alice", tid)
    result = tl.cancel_task(tid)
    assert result["ok"] is True


def test_cancel_task_from_done_blocked():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    tl.claim_task("alice", tid)
    tl.start_work("alice", tid)
    tl.complete_task("alice", tid)
    result = tl.cancel_task(tid)
    assert result["ok"] is False
    assert "terminal" in result["reason"]


# ── cancel_all tests ────────────────────────────────────

def test_cancel_all():
    tl, tmp = make_tl()
    tl.create_task({"directive": "task 1"}, task_id="t1")
    tl.create_task({"directive": "task 2"}, task_id="t2")
    tl.claim_task("alice", "t1")
    tl.claim_task("alice", "t2")
    result = tl.cancel_all("alice")
    assert result["ok"] is True
    assert result["count"] == 2


def test_cancel_all_leaves_other_agents():
    tl, tmp = make_tl()
    tl.create_task({"directive": "alice task"}, task_id="a1")
    tl.create_task({"directive": "bob task"}, task_id="b1")
    tl.claim_task("alice", "a1")
    tl.claim_task("bob", "b1")
    result = tl.cancel_all("alice")
    assert result["count"] == 1
    # Bob's task should still be claimed
    state = tl.get_state("b1")
    assert state["state"] == TaskState.CLAIMED.value


# ── get_state tests ─────────────────────────────────────

def test_get_state_returns_full_record():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    state = tl.get_state(tid)
    assert state["task_id"] == tid
    assert "spec" in state
    assert "state" in state
    assert "history" in state


def test_get_state_nonexistent():
    tl, tmp = make_tl()
    state = tl.get_state("nonexistent")
    assert state is None


# ── list_tasks tests ────────────────────────────────────

def test_list_tasks_all():
    tl, tmp = make_tl()
    tl.create_task({"directive": "task 1"}, task_id="t1")
    tl.create_task({"directive": "task 2"}, task_id="t2")
    tasks = tl.list_tasks()
    assert len(tasks) == 2


def test_list_tasks_filter_by_agent():
    tl, tmp = make_tl()
    tl.create_task({"directive": "alice task"}, task_id="a1")
    tl.create_task({"directive": "bob task"}, task_id="b1")
    tl.claim_task("alice", "a1")
    tl.claim_task("bob", "b1")
    alice_tasks = tl.list_tasks(agent_id="alice")
    assert len(alice_tasks) == 1
    assert alice_tasks[0]["task_id"] == "a1"


def test_list_tasks_filter_by_state():
    tl, tmp = make_tl()
    tl.create_task({"directive": "task 1"}, task_id="t1")
    tl.create_task({"directive": "task 2"}, task_id="t2")
    tl.claim_task("alice", "t1")
    pending = tl.list_tasks(state="pending")
    claimed = tl.list_tasks(state="claimed")
    assert len(pending) == 1
    assert len(claimed) == 1


# ── Invalid transition tests ────────────────────────────

def test_invalid_transition_done_to_anything():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    tl.claim_task("alice", tid)
    tl.start_work("alice", tid)
    tl.complete_task("alice", tid)
    # Try to claim a done task
    result = tl.claim_task("bob", tid)
    assert result["ok"] is False


def test_invalid_transition_cancelled_to_anything():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    tl.cancel_task(tid)
    result = tl.claim_task("alice", tid)
    assert result["ok"] is False


# ── History tests ───────────────────────────────────────

def test_history_records_transitions():
    tl, tmp = make_tl()
    tid = tl.create_task({"directive": "do something"})
    tl.claim_task("alice", tid)
    tl.start_work("alice", tid)
    tl.complete_task("alice", tid)
    state = tl.get_state(tid)
    history = state["history"]
    assert len(history) == 4  # create, claim, start, complete
    assert history[0]["to_state"] == "pending"
    assert history[1]["to_state"] == "claimed"
    assert history[2]["to_state"] == "in_progress"
    assert history[3]["to_state"] == "done"
