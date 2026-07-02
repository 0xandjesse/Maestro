"""Tests for the Session Checkpoint module.

Covers:
* save/restore roundtrip
* list checkpoints (newest first)
* prune (keep last N)
* missing agent (restore returns None, list returns [])
* empty state
* atomic writes (no partial files)
* schema validation
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from nucleus.modules.session_checkpoint import (
    FileSessionCheckpoint,
    SessionState,
    validate_state,
)


# ── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def tmp_data_dir():
    """Create a temp directory for isolated checkpoint storage."""
    with tempfile.TemporaryDirectory(prefix="test_checkpoints_") as td:
        yield td


@pytest.fixture
def store(tmp_data_dir):
    """Return a FileSessionCheckpoint pointed at a temp directory."""
    return FileSessionCheckpoint(data_dir=tmp_data_dir)


@pytest.fixture
def sample_state():
    """Return a representative SessionState."""
    return SessionState(
        agent_id="cactus-jack",
        session_id="sess-abc123",
        active_tasks=["task-1", "task-2"],
        context_summary="Working on module 12",
        last_message_id="msg-99",
        version=1,
    )


# ── save / restore roundtrip ───────────────────────────────────────────


class TestSaveRestore:
    def test_save_returns_checkpoint_id(self, store, sample_state):
        cid = store.save("cactus-jack", sample_state)
        assert isinstance(cid, str)
        assert len(cid) > 0
        # Should be a numeric timestamp
        assert cid.isdigit()

    def test_roundtrip_preserves_data(self, store, sample_state):
        store.save("cactus-jack", sample_state)
        restored = store.restore("cactus-jack")
        assert restored is not None
        assert restored.agent_id == "cactus-jack"
        assert restored.session_id == "sess-abc123"
        assert restored.active_tasks == ["task-1", "task-2"]
        assert restored.context_summary == "Working on module 12"
        assert restored.last_message_id == "msg-99"
        assert restored.version == 1
        assert restored.checkpointed_at > 0

    def test_restore_returns_latest(self, store, sample_state):
        import time
        store.save("cactus-jack", sample_state)
        time.sleep(0.01)
        sample_state.context_summary = "Updated context"
        store.save("cactus-jack", sample_state)

        restored = store.restore("cactus-jack")
        assert restored is not None
        assert restored.context_summary == "Updated context"

    def test_restore_missing_agent_returns_none(self, store):
        result = store.restore("nonexistent")
        assert result is None

    def test_save_empty_agent_id_raises(self, store, sample_state):
        with pytest.raises(ValueError, match="agent_id"):
            store.save("", sample_state)


# ── list checkpoints ───────────────────────────────────────────────────


class TestListCheckpoints:
    def test_list_empty_for_missing_agent(self, store):
        result = store.list_checkpoints("nonexistent")
        assert result == []

    def test_list_returns_all_newest_first(self, store, sample_state):
        import time
        cid1 = store.save("cactus-jack", sample_state)
        time.sleep(0.01)
        sample_state.context_summary = "Second checkpoint"
        cid2 = store.save("cactus-jack", sample_state)
        time.sleep(0.01)
        sample_state.context_summary = "Third checkpoint"
        cid3 = store.save("cactus-jack", sample_state)

        checkpoints = store.list_checkpoints("cactus-jack")
        assert len(checkpoints) == 3
        # Newest first
        assert checkpoints[0].checkpointed_at == int(cid3)
        assert checkpoints[1].checkpointed_at == int(cid2)
        assert checkpoints[2].checkpointed_at == int(cid1)

    def test_list_returns_sessionstate_objects(self, store, sample_state):
        store.save("cactus-jack", sample_state)
        checkpoints = store.list_checkpoints("cactus-jack")
        assert len(checkpoints) == 1
        assert isinstance(checkpoints[0], SessionState)


# ── prune ──────────────────────────────────────────────────────────────


class TestPrune:
    def test_prune_keeps_last_n(self, store, sample_state):
        import time
        for i in range(10):
            sample_state.context_summary = f"Checkpoint {i}"
            store.save("cactus-jack", sample_state)
            time.sleep(0.01)

        pruned = store.prune("cactus-jack", keep=3)
        assert pruned == 7

        remaining = store.list_checkpoints("cactus-jack")
        assert len(remaining) == 3

    def test_prune_noop_when_under_limit(self, store, sample_state):
        store.save("cactus-jack", sample_state)
        pruned = store.prune("cactus-jack", keep=5)
        assert pruned == 0
        assert len(store.list_checkpoints("cactus-jack")) == 1

    def test_prune_missing_agent_returns_zero(self, store):
        pruned = store.prune("nonexistent", keep=5)
        assert pruned == 0

    def test_prune_keep_zero_deletes_all(self, store, sample_state):
        import time
        for i in range(3):
            store.save("cactus-jack", sample_state)
            time.sleep(0.01)

        pruned = store.prune("cactus-jack", keep=0)
        assert pruned == 3
        assert store.list_checkpoints("cactus-jack") == []

    def test_prune_negative_keep_raises(self, store):
        with pytest.raises(ValueError, match="keep"):
            store.prune("cactus-jack", keep=-1)


# ── empty state ────────────────────────────────────────────────────────


class TestEmptyState:
    def test_save_empty_state(self, store):
        state = SessionState(
            agent_id="test-agent",
            session_id="sess-empty",
        )
        cid = store.save("test-agent", state)
        restored = store.restore("test-agent")
        assert restored is not None
        assert restored.active_tasks == []
        assert restored.context_summary == ""
        assert restored.last_message_id is None
        assert restored.version == 1


# ── atomic writes ──────────────────────────────────────────────────────


class TestAtomicWrites:
    def test_no_tmp_files_left_behind(self, store, sample_state, tmp_data_dir):
        store.save("cactus-jack", sample_state)

        agent_dir = Path(tmp_data_dir) / "cactus-jack"
        tmp_files = list(agent_dir.glob("*.tmp"))
        assert len(tmp_files) == 0, f"tmp files left behind: {tmp_files}"

    def test_checkpoint_file_is_valid_json(self, store, sample_state, tmp_data_dir):
        store.save("cactus-jack", sample_state)

        agent_dir = Path(tmp_data_dir) / "cactus-jack"
        json_files = list(agent_dir.glob("*.json"))
        assert len(json_files) == 1

        raw = json_files[0].read_text()
        data = json.loads(raw)
        assert data["agent_id"] == "cactus-jack"
        assert data["session_id"] == "sess-abc123"

    def test_multiple_saves_no_corruption(self, store, sample_state, tmp_data_dir):
        import time
        for i in range(5):
            sample_state.context_summary = f"Checkpoint {i}"
            store.save("cactus-jack", sample_state)
            time.sleep(0.01)

        agent_dir = Path(tmp_data_dir) / "cactus-jack"
        json_files = sorted(agent_dir.glob("*.json"))
        assert len(json_files) == 5

        for f in json_files:
            raw = f.read_text()
            data = json.loads(raw)
            assert data["agent_id"] == "cactus-jack"
            assert "context_summary" in data


# ── schema validation ─────────────────────────────────────────────────


class TestSchemaValidation:
    def test_valid_state(self):
        errors = validate_state({
            "agent_id": "cactus-jack",
            "session_id": "sess-1",
            "active_tasks": ["task-1"],
            "context_summary": "working",
            "last_message_id": "msg-1",
            "checkpointed_at": 1000,
            "version": 1,
        })
        assert errors == []

    def test_missing_agent_id(self):
        errors = validate_state({
            "session_id": "sess-1",
            "active_tasks": [],
            "context_summary": "",
            "checkpointed_at": 0,
            "version": 1,
        })
        assert any("agent_id" in e for e in errors)

    def test_missing_session_id(self):
        errors = validate_state({
            "agent_id": "test",
            "active_tasks": [],
            "context_summary": "",
            "checkpointed_at": 0,
            "version": 1,
        })
        assert any("session_id" in e for e in errors)

    def test_bad_active_tasks(self):
        errors = validate_state({
            "agent_id": "test",
            "session_id": "sess-1",
            "active_tasks": "not-a-list",
            "context_summary": "",
            "checkpointed_at": 0,
            "version": 1,
        })
        assert any("active_tasks" in e for e in errors)

    def test_bad_checkpointed_at(self):
        errors = validate_state({
            "agent_id": "test",
            "session_id": "sess-1",
            "active_tasks": [],
            "context_summary": "",
            "checkpointed_at": -1,
            "version": 1,
        })
        assert any("checkpointed_at" in e for e in errors)

    def test_bad_version(self):
        errors = validate_state({
            "agent_id": "test",
            "session_id": "sess-1",
            "active_tasks": [],
            "context_summary": "",
            "checkpointed_at": 0,
            "version": "not-an-int",
        })
        assert any("version" in e for e in errors)

    def test_not_a_dict(self):
        errors = validate_state("not a dict")
        assert any("not a dict" in e for e in errors)


# ── data directory creation ────────────────────────────────────────────


class TestDataDirectory:
    def test_creates_data_dir_if_missing(self):
        with tempfile.TemporaryDirectory(prefix="test_ckpt_") as td:
            data_dir = Path(td) / "nested" / "checkpoints"
            assert not data_dir.exists()

            store = FileSessionCheckpoint(data_dir=str(data_dir))
            assert data_dir.exists()
            assert data_dir.is_dir()

    def test_creates_agent_dir_on_save(self, store, sample_state, tmp_data_dir):
        agent_dir = Path(tmp_data_dir) / "new-agent"
        assert not agent_dir.exists()

        store.save("new-agent", sample_state)
        assert agent_dir.exists()
        assert agent_dir.is_dir()


# ── multiple agents ────────────────────────────────────────────────────


class TestMultipleAgents:
    def test_agents_isolated(self, store):
        state_a = SessionState(
            agent_id="agent-a", session_id="sess-a",
            context_summary="Agent A context",
        )
        state_b = SessionState(
            agent_id="agent-b", session_id="sess-b",
            context_summary="Agent B context",
        )

        store.save("agent-a", state_a)
        store.save("agent-b", state_b)

        restored_a = store.restore("agent-a")
        restored_b = store.restore("agent-b")

        assert restored_a is not None
        assert restored_a.context_summary == "Agent A context"
        assert restored_b is not None
        assert restored_b.context_summary == "Agent B context"

    def test_list_per_agent(self, store):
        import time
        for i in range(3):
            store.save("agent-a", SessionState(
                agent_id="agent-a", session_id=f"sess-a-{i}",
            ))
            time.sleep(0.01)
        for i in range(2):
            store.save("agent-b", SessionState(
                agent_id="agent-b", session_id=f"sess-b-{i}",
            ))
            time.sleep(0.01)

        assert len(store.list_checkpoints("agent-a")) == 3
        assert len(store.list_checkpoints("agent-b")) == 2

    def test_prune_per_agent(self, store):
        import time
        for i in range(5):
            store.save("agent-a", SessionState(
                agent_id="agent-a", session_id=f"sess-a-{i}",
            ))
            time.sleep(0.01)
        for i in range(5):
            store.save("agent-b", SessionState(
                agent_id="agent-b", session_id=f"sess-b-{i}",
            ))
            time.sleep(0.01)

        pruned_a = store.prune("agent-a", keep=2)
        pruned_b = store.prune("agent-b", keep=3)

        assert pruned_a == 3
        assert pruned_b == 2
        assert len(store.list_checkpoints("agent-a")) == 2
        assert len(store.list_checkpoints("agent-b")) == 3
