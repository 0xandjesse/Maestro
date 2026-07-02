"""Tests for the Registry Manager module.

Covers:
* Basic CRUD (register, lookup, unregister, list_all)
* Schema validation (rejects malformed entries)
* Single-writer lock (concurrent write safety)
* Crash recovery (WAL replay)
* Backward compatibility (reads existing ~/.maestro/registry.json)
"""

from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
import time
from pathlib import Path

import pytest

from registry_manager import (
    AgentRecord,
    FileRegistryManager,
    validate_record,
    validate_registry,
)


# ── fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def tmp_registry_path():
    """Create a temp file path for an isolated registry."""
    fd, path = tempfile.mkstemp(suffix=".json", prefix="test_registry_")
    os.close(fd)
    # Start with an empty registry
    Path(path).write_text("[]")
    yield path
    # Cleanup
    for suffix in ("", ".wal", ".tmp"):
        p = Path(path + suffix) if suffix else Path(path)
        if p.exists():
            p.unlink(missing_ok=True)


@pytest.fixture
def manager(tmp_registry_path):
    """Return a FileRegistryManager pointed at a temp file."""
    return FileRegistryManager(tmp_registry_path)


# ── basic CRUD ─────────────────────────────────────────────────────────

class TestBasicCRUD:
    def test_register_and_lookup(self, manager):
        record = manager.register("agent-1", "http://127.0.0.1:9000/message")
        assert record.agentId == "agent-1"
        assert record.webhookEndpoint == "http://127.0.0.1:9000/message"
        assert record.status == "active"
        assert record.registeredAt > 0

        found = manager.lookup("agent-1")
        assert found is not None
        assert found.agentId == "agent-1"

    def test_lookup_missing(self, manager):
        assert manager.lookup("nobody") is None

    def test_register_overwrite(self, manager):
        manager.register("agent-1", "http://127.0.0.1:9000/message")
        manager.register("agent-1", "http://127.0.0.1:9001/message")
        found = manager.lookup("agent-1")
        assert found is not None
        assert found.webhookEndpoint == "http://127.0.0.1:9001/message"

    def test_unregister(self, manager):
        manager.register("agent-1", "http://127.0.0.1:9000/message")
        assert manager.unregister("agent-1") is True
        assert manager.lookup("agent-1") is None

    def test_unregister_missing(self, manager):
        assert manager.unregister("nobody") is False

    def test_list_all(self, manager):
        manager.register("a", "http://a")
        manager.register("b", "http://b")
        all_records = manager.list_all()
        assert len(all_records) == 2
        ids = {r.agentId for r in all_records}
        assert ids == {"a", "b"}

    def test_update_last_seen(self, manager):
        manager.register("agent-1", "http://127.0.0.1:9000/message")
        time.sleep(0.01)  # ensure timestamp changes
        assert manager.update_last_seen("agent-1") is True
        found = manager.lookup("agent-1")
        assert found is not None
        assert found.lastSeen > found.registeredAt

    def test_update_last_seen_missing(self, manager):
        assert manager.update_last_seen("nobody") is False

    def test_set_status(self, manager):
        manager.register("agent-1", "http://127.0.0.1:9000/message")
        assert manager.set_status("agent-1", "inactive") is True
        found = manager.lookup("agent-1")
        assert found is not None
        assert found.status == "inactive"

    def test_set_status_missing(self, manager):
        assert manager.set_status("nobody", "inactive") is False

    def test_register_with_capabilities(self, manager):
        record = manager.register(
            "agent-1", "http://127.0.0.1:9000/message",
            capabilities=["chat", "search"],
        )
        assert record.capabilities == ["chat", "search"]


# ── schema validation ──────────────────────────────────────────────────

class TestSchemaValidation:
    def test_valid_record(self):
        errors = validate_record({
            "agentId": "test",
            "webhookEndpoint": "http://x",
        })
        assert errors == []

    def test_missing_agent_id(self):
        errors = validate_record({"webhookEndpoint": "http://x"})
        assert any("agentId" in e for e in errors)

    def test_missing_webhook(self):
        errors = validate_record({"agentId": "test"})
        assert any("webhookEndpoint" in e for e in errors)

    def test_empty_agent_id(self):
        errors = validate_record({"agentId": "", "webhookEndpoint": "http://x"})
        assert any("agentId" in e for e in errors)

    def test_bad_capabilities(self):
        errors = validate_record({
            "agentId": "test",
            "webhookEndpoint": "http://x",
            "capabilities": "not-a-list",
        })
        assert any("capabilities" in e for e in errors)

    def test_bad_status(self):
        errors = validate_record({
            "agentId": "test",
            "webhookEndpoint": "http://x",
            "status": "bogus",
        })
        assert any("status" in e for e in errors)

    def test_valid_statuses(self):
        for status in ("active", "inactive", "suspended", "error"):
            errors = validate_record({
                "agentId": "test",
                "webhookEndpoint": "http://x",
                "status": status,
            })
            assert errors == [], f"status {status!r} should be valid"

    def test_duplicate_agent_ids(self):
        errors = validate_registry([
            {"agentId": "dup", "webhookEndpoint": "http://a"},
            {"agentId": "dup", "webhookEndpoint": "http://b"},
        ])
        assert any("duplicate" in e for e in errors)

    def test_not_a_list(self):
        errors = validate_registry({"not": "a list"})
        assert any("array" in e for e in errors)

    def test_register_rejects_invalid(self, manager):
        """Directly write bad data and verify _save rejects it."""
        with pytest.raises(ValueError, match="schema validation failed"):
            manager._save([{"agentId": "", "webhookEndpoint": ""}])


# ── concurrent write safety ────────────────────────────────────────────

def _concurrent_writer(registry_path, agent_id, results_queue):
    """Worker function for concurrent write test."""
    try:
        mgr = FileRegistryManager(registry_path)
        mgr.register(agent_id, f"http://{agent_id}")
        # Verify our write survived
        found = mgr.lookup(agent_id)
        results_queue.put(("ok", agent_id, found is not None))
    except Exception as exc:
        results_queue.put(("error", agent_id, str(exc)))


class TestConcurrentWrite:
    def test_concurrent_registration(self, tmp_registry_path):
        """Multiple processes register agents concurrently — no corruption."""
        num_workers = 8
        results_queue: multiprocessing.Queue = multiprocessing.Queue()
        processes = []

        for i in range(num_workers):
            p = multiprocessing.Process(
                target=_concurrent_writer,
                args=(tmp_registry_path, f"agent-{i}", results_queue),
            )
            processes.append(p)
            p.start()

        for p in processes:
            p.join(timeout=10)

        # Collect results
        results = []
        while not results_queue.empty():
            results.append(results_queue.get())

        errors = [r for r in results if r[0] == "error"]
        assert errors == [], f"concurrent writers had errors: {errors}"

        # All agents should be present
        mgr = FileRegistryManager(tmp_registry_path)
        all_records = mgr.list_all()
        ids = {r.agentId for r in all_records}
        expected = {f"agent-{i}" for i in range(num_workers)}
        assert ids == expected, f"missing agents: {expected - ids}"

    def test_no_corrupted_json(self, tmp_registry_path):
        """After concurrent writes, the file is valid JSON."""
        # Run the concurrent test
        num_workers = 6
        processes = []
        for i in range(num_workers):
            p = multiprocessing.Process(
                target=_concurrent_writer,
                args=(tmp_registry_path, f"agent-{i}", multiprocessing.Queue()),
            )
            processes.append(p)
            p.start()
        for p in processes:
            p.join(timeout=10)

        # File must be parseable JSON
        raw = Path(tmp_registry_path).read_text()
        data = json.loads(raw)
        assert isinstance(data, list)
        # Every entry must have required fields
        for entry in data:
            assert isinstance(entry.get("agentId"), str)
            assert isinstance(entry.get("webhookEndpoint"), str)


# ── crash recovery (WAL) ───────────────────────────────────────────────

class TestCrashRecovery:
    def test_wal_replay_on_init(self, tmp_registry_path):
        """A WAL with pending entries is replayed on startup."""
        mgr = FileRegistryManager(tmp_registry_path)

        # Simulate a crash: write to WAL but don't complete the save
        mgr._wal_append("register", {
            "agentId": "orphan",
            "webhookEndpoint": "http://orphan",
            "capabilities": [],
            "registeredAt": int(time.time() * 1000),
            "lastSeen": int(time.time() * 1000),
            "status": "active",
        })

        # Verify the WAL file exists and has content
        assert mgr._wal_path.exists()
        assert mgr._wal_path.read_text().strip() != ""

        # Create a new manager — it should replay the WAL
        mgr2 = FileRegistryManager(tmp_registry_path)
        found = mgr2.lookup("orphan")
        assert found is not None, "WAL replay should recover orphaned registration"
        assert found.agentId == "orphan"

        # WAL should be cleared after successful replay
        assert mgr2._wal_path.read_text().strip() == ""

    def test_wal_cleared_after_successful_write(self, manager):
        """After a successful register, the WAL is empty."""
        manager.register("agent-1", "http://127.0.0.1:9000/message")
        wal_content = manager._wal_path.read_text().strip()
        assert wal_content == "", f"WAL should be empty after successful write, got: {wal_content!r}"

    def test_wal_replay_with_existing_data(self, tmp_registry_path):
        """WAL replay merges with existing registry data."""
        mgr = FileRegistryManager(tmp_registry_path)
        mgr.register("existing", "http://existing")

        # Simulate crash with a new registration in WAL
        mgr._wal_append("register", {
            "agentId": "crashed",
            "webhookEndpoint": "http://crashed",
            "capabilities": [],
            "registeredAt": int(time.time() * 1000),
            "lastSeen": int(time.time() * 1000),
            "status": "active",
        })

        mgr2 = FileRegistryManager(tmp_registry_path)
        all_records = mgr2.list_all()
        ids = {r.agentId for r in all_records}
        assert ids == {"existing", "crashed"}


# ── backward compatibility ────────────────────────────────────────────

class TestBackwardCompatibility:
    def test_read_existing_registry(self):
        """Read the real ~/.maestro/registry.json if it exists."""
        real_path = os.path.expanduser("~/.maestro/registry.json")
        if not os.path.exists(real_path):
            pytest.skip("~/.maestro/registry.json not found")

        mgr = FileRegistryManager(real_path)
        records = mgr.list_all()
        assert len(records) > 0, "existing registry should have entries"

        # Every record should be a valid AgentRecord
        for r in records:
            assert isinstance(r, AgentRecord)
            assert r.agentId
            assert r.webhookEndpoint

        # Lookup a known agent
        found = mgr.lookup("cactus-jack")
        assert found is not None, "cactus-jack should be in the registry"
        assert found.agentId == "cactus-jack"

    def test_roundtrip_existing_format(self, tmp_registry_path):
        """Write in the existing format and read back correctly."""
        existing_format = [
            {
                "agentId": "chatterbox",
                "webhookEndpoint": "http://127.0.0.1:3853/message",
                "capabilities": [],
                "registeredAt": 1782594130732,
                "publicKey": "1e463070b587ffbe895d99642c2072b24b4b907abc603df39a50d085b18c3b6b",
            }
        ]
        Path(tmp_registry_path).write_text(json.dumps(existing_format, indent=2))

        mgr = FileRegistryManager(tmp_registry_path)
        records = mgr.list_all()
        assert len(records) == 1
        r = records[0]
        assert r.agentId == "chatterbox"
        assert r.publicKey == "1e463070b587ffbe895d99642c2072b24b4b907abc603df39a50d085b18c3b6b"
        assert r.registeredAt == 1782594130732


# ── atomic replace ─────────────────────────────────────────────────────

class TestAtomicReplace:
    def test_no_partial_write(self, tmp_registry_path):
        """If a write fails mid-stream, the file is not corrupted."""
        mgr = FileRegistryManager(tmp_registry_path)
        mgr.register("agent-1", "http://127.0.0.1:9000/message")

        # Read the valid state
        before = Path(tmp_registry_path).read_text()
        data_before = json.loads(before)
        assert len(data_before) == 1

        # Attempt an invalid write — should raise and leave file unchanged
        with pytest.raises(ValueError):
            mgr._save([{"agentId": "", "webhookEndpoint": ""}])

        after = Path(tmp_registry_path).read_text()
        data_after = json.loads(after)
        assert data_after == data_before, "file should be unchanged after failed write"

    def test_temp_file_cleaned_up(self, tmp_registry_path):
        """No .tmp file left behind after a successful write."""
        mgr = FileRegistryManager(tmp_registry_path)
        mgr.register("agent-1", "http://127.0.0.1:9000/message")

        tmp_path = Path(str(tmp_registry_path) + ".tmp")
        assert not tmp_path.exists(), f"temp file {tmp_path} should not exist"
