"""Standalone test runner — no pytest dependency.

Runs all tests in test_manager.py via direct execution.
"""

import sys
import os
import json
import tempfile
import time
import traceback
import multiprocessing
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from nucleus.modules.registry_manager import (
    AgentRecord,
    FileRegistryManager,
    validate_record,
    validate_registry,
)

PASS = 0
FAIL = 0
ERRORS = []


def test(name):
    """Decorator-like: run the function, record pass/fail."""
    global PASS, FAIL
    def decorator(fn):
        try:
            fn()
            PASS += 1
            print(f"  PASS  {name}")
        except Exception as e:
            FAIL += 1
            ERRORS.append((name, str(e), traceback.format_exc()))
            print(f"  FAIL  {name}: {e}")
        return fn
    return decorator


def make_temp_registry():
    fd, path = tempfile.mkstemp(suffix=".json", prefix="test_registry_")
    os.close(fd)
    Path(path).write_text("[]")
    return path


def cleanup_registry(path):
    for suffix in ("", ".wal", ".tmp"):
        p = Path(path + suffix) if suffix else Path(path)
        if p.exists():
            p.unlink(missing_ok=True)


# ── Basic CRUD ─────────────────────────────────────────────────────────

@test("register and lookup")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        record = mgr.register("agent-1", "http://127.0.0.1:9000/message")
        assert record.agentId == "agent-1"
        assert record.webhookEndpoint == "http://127.0.0.1:9000/message"
        assert record.status == "active"
        assert record.registeredAt > 0
        found = mgr.lookup("agent-1")
        assert found is not None
        assert found.agentId == "agent-1"
    finally:
        cleanup_registry(path)


@test("lookup missing")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        assert mgr.lookup("nobody") is None
    finally:
        cleanup_registry(path)


@test("register overwrite")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        mgr.register("agent-1", "http://127.0.0.1:9000/message")
        mgr.register("agent-1", "http://127.0.0.1:9001/message")
        found = mgr.lookup("agent-1")
        assert found is not None
        assert found.webhookEndpoint == "http://127.0.0.1:9001/message"
    finally:
        cleanup_registry(path)


@test("unregister")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        mgr.register("agent-1", "http://127.0.0.1:9000/message")
        assert mgr.unregister("agent-1") is True
        assert mgr.lookup("agent-1") is None
    finally:
        cleanup_registry(path)


@test("unregister missing")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        assert mgr.unregister("nobody") is False
    finally:
        cleanup_registry(path)


@test("list all")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        mgr.register("a", "http://a")
        mgr.register("b", "http://b")
        all_records = mgr.list_all()
        assert len(all_records) == 2
        ids = {r.agentId for r in all_records}
        assert ids == {"a", "b"}
    finally:
        cleanup_registry(path)


@test("update last seen")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        mgr.register("agent-1", "http://127.0.0.1:9000/message")
        time.sleep(0.01)
        assert mgr.update_last_seen("agent-1") is True
        found = mgr.lookup("agent-1")
        assert found is not None
        assert found.lastSeen > found.registeredAt
    finally:
        cleanup_registry(path)


@test("update last seen missing")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        assert mgr.update_last_seen("nobody") is False
    finally:
        cleanup_registry(path)


@test("set status")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        mgr.register("agent-1", "http://127.0.0.1:9000/message")
        assert mgr.set_status("agent-1", "inactive") is True
        found = mgr.lookup("agent-1")
        assert found is not None
        assert found.status == "inactive"
    finally:
        cleanup_registry(path)


@test("set status missing")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        assert mgr.set_status("nobody", "inactive") is False
    finally:
        cleanup_registry(path)


@test("register with capabilities")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        record = mgr.register("agent-1", "http://127.0.0.1:9000/message", capabilities=["chat", "search"])
        assert record.capabilities == ["chat", "search"]
    finally:
        cleanup_registry(path)


# ── Schema Validation ──────────────────────────────────────────────────

@test("valid record")
def _():
    errors = validate_record({"agentId": "test", "webhookEndpoint": "http://x"})
    assert errors == []


@test("missing agent id")
def _():
    errors = validate_record({"webhookEndpoint": "http://x"})
    assert any("agentId" in e for e in errors)


@test("missing webhook")
def _():
    errors = validate_record({"agentId": "test"})
    assert any("webhookEndpoint" in e for e in errors)


@test("empty agent id")
def _():
    errors = validate_record({"agentId": "", "webhookEndpoint": "http://x"})
    assert any("agentId" in e for e in errors)


@test("bad capabilities")
def _():
    errors = validate_record({"agentId": "test", "webhookEndpoint": "http://x", "capabilities": "not-a-list"})
    assert any("capabilities" in e for e in errors)


@test("bad status")
def _():
    errors = validate_record({"agentId": "test", "webhookEndpoint": "http://x", "status": "bogus"})
    assert any("status" in e for e in errors)


@test("valid statuses")
def _():
    for status in ("active", "inactive", "suspended", "error"):
        errors = validate_record({"agentId": "test", "webhookEndpoint": "http://x", "status": status})
        assert errors == [], f"status {status!r} should be valid"


@test("duplicate agent ids")
def _():
    errors = validate_registry([
        {"agentId": "dup", "webhookEndpoint": "http://a"},
        {"agentId": "dup", "webhookEndpoint": "http://b"},
    ])
    assert any("duplicate" in e for e in errors)


@test("not a list")
def _():
    errors = validate_registry({"not": "a list"})
    assert any("array" in e for e in errors)


@test("register rejects invalid")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        try:
            mgr._save([{"agentId": "", "webhookEndpoint": ""}])
            assert False, "should have raised ValueError"
        except ValueError as e:
            assert "schema validation failed" in str(e)
    finally:
        cleanup_registry(path)


# ── Concurrent Write Safety ────────────────────────────────────────────

def _concurrent_writer(registry_path, agent_id, results_queue):
    try:
        mgr = FileRegistryManager(registry_path)
        mgr.register(agent_id, f"http://{agent_id}")
        found = mgr.lookup(agent_id)
        results_queue.put(("ok", agent_id, found is not None))
    except Exception as exc:
        results_queue.put(("error", agent_id, str(exc)))


@test("concurrent registration")
def _():
    path = make_temp_registry()
    try:
        num_workers = 8
        results_queue = multiprocessing.Queue()
        processes = []
        for i in range(num_workers):
            p = multiprocessing.Process(
                target=_concurrent_writer,
                args=(path, f"agent-{i}", results_queue),
            )
            processes.append(p)
            p.start()
        for p in processes:
            p.join(timeout=10)
        results = []
        while not results_queue.empty():
            results.append(results_queue.get())
        errors = [r for r in results if r[0] == "error"]
        assert errors == [], f"concurrent writers had errors: {errors}"
        mgr = FileRegistryManager(path)
        all_records = mgr.list_all()
        ids = {r.agentId for r in all_records}
        expected = {f"agent-{i}" for i in range(num_workers)}
        assert ids == expected, f"missing agents: {expected - ids}"
    finally:
        cleanup_registry(path)


@test("no corrupted json after concurrent writes")
def _():
    path = make_temp_registry()
    try:
        num_workers = 6
        processes = []
        for i in range(num_workers):
            p = multiprocessing.Process(
                target=_concurrent_writer,
                args=(path, f"agent-{i}", multiprocessing.Queue()),
            )
            processes.append(p)
            p.start()
        for p in processes:
            p.join(timeout=10)
        raw = Path(path).read_text()
        data = json.loads(raw)
        assert isinstance(data, list)
        for entry in data:
            assert isinstance(entry.get("agentId"), str)
            assert isinstance(entry.get("webhookEndpoint"), str)
    finally:
        cleanup_registry(path)


# ── Crash Recovery (WAL) ───────────────────────────────────────────────

@test("WAL replay on init")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        mgr._wal_append("register", {
            "agentId": "orphan",
            "webhookEndpoint": "http://orphan",
            "capabilities": [],
            "registeredAt": int(time.time() * 1000),
            "lastSeen": int(time.time() * 1000),
            "status": "active",
        })
        assert mgr._wal_path.exists()
        assert mgr._wal_path.read_text().strip() != ""
        mgr2 = FileRegistryManager(path)
        found = mgr2.lookup("orphan")
        assert found is not None, "WAL replay should recover orphaned registration"
        assert found.agentId == "orphan"
        assert mgr2._wal_path.read_text().strip() == ""
    finally:
        cleanup_registry(path)


@test("WAL cleared after successful write")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        mgr.register("agent-1", "http://127.0.0.1:9000/message")
        wal_content = mgr._wal_path.read_text().strip()
        assert wal_content == "", f"WAL should be empty, got: {wal_content!r}"
    finally:
        cleanup_registry(path)


@test("WAL replay with existing data")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        mgr.register("existing", "http://existing")
        mgr._wal_append("register", {
            "agentId": "crashed",
            "webhookEndpoint": "http://crashed",
            "capabilities": [],
            "registeredAt": int(time.time() * 1000),
            "lastSeen": int(time.time() * 1000),
            "status": "active",
        })
        mgr2 = FileRegistryManager(path)
        all_records = mgr2.list_all()
        ids = {r.agentId for r in all_records}
        assert ids == {"existing", "crashed"}
    finally:
        cleanup_registry(path)


# ── Backward Compatibility ────────────────────────────────────────────

@test("read existing registry")
def _():
    real_path = os.path.expanduser("~/.maestro/registry.json")
    if not os.path.exists(real_path):
        print("    (skipped — ~/.maestro/registry.json not found)")
        return
    mgr = FileRegistryManager(real_path)
    records = mgr.list_all()
    assert len(records) > 0
    for r in records:
        assert isinstance(r, AgentRecord)
        assert r.agentId
        assert r.webhookEndpoint
    found = mgr.lookup("cactus-jack")
    assert found is not None
    assert found.agentId == "cactus-jack"


@test("roundtrip existing format")
def _():
    path = make_temp_registry()
    try:
        existing_format = [{
            "agentId": "chatterbox",
            "webhookEndpoint": "http://127.0.0.1:3853/message",
            "capabilities": [],
            "registeredAt": 1782594130732,
            "publicKey": "1e463070b587ffbe895d99642c2072b24b4b907abc603df39a50d085b18c3b6b",
        }]
        Path(path).write_text(json.dumps(existing_format, indent=2))
        mgr = FileRegistryManager(path)
        records = mgr.list_all()
        assert len(records) == 1
        r = records[0]
        assert r.agentId == "chatterbox"
        assert r.publicKey == "1e463070b587ffbe895d99642c2072b24b4b907abc603df39a50d085b18c3b6b"
        assert r.registeredAt == 1782594130732
    finally:
        cleanup_registry(path)


# ── Atomic Replace ─────────────────────────────────────────────────────

@test("no partial write on failure")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        mgr.register("agent-1", "http://127.0.0.1:9000/message")
        before = Path(path).read_text()
        data_before = json.loads(before)
        assert len(data_before) == 1
        try:
            mgr._save([{"agentId": "", "webhookEndpoint": ""}])
            assert False, "should have raised"
        except ValueError:
            pass
        after = Path(path).read_text()
        data_after = json.loads(after)
        assert data_after == data_before, "file should be unchanged after failed write"
    finally:
        cleanup_registry(path)


@test("temp file cleaned up")
def _():
    path = make_temp_registry()
    try:
        mgr = FileRegistryManager(path)
        mgr.register("agent-1", "http://127.0.0.1:9000/message")
        tmp_path = Path(str(path) + ".tmp")
        assert not tmp_path.exists(), f"temp file {tmp_path} should not exist"
    finally:
        cleanup_registry(path)


# ── Run ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\nRegistry Manager — Test Suite\n{'='*50}")
    total = PASS + FAIL
    print(f"\nResults: {PASS} passed, {FAIL} failed, {total} total\n")
    if ERRORS:
        print("Failures:")
        for name, msg, tb in ERRORS:
            print(f"\n  [{name}]")
            print(f"  {msg}")
    if FAIL:
        sys.exit(1)
    print("All tests passed.")
