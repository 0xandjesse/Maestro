# test_gate_engine.py — 12+ tests for Gate Engine (M03)

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Add the runtime directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "code" / "runtime" / "message_router"))

from gate_engine import (
    GateEngine, GateResult, GateDecision,
    ArtifactGate, DependencyGate, TimeGate,
)


class FakeTaskLifecycle:
    """Minimal fake for testing DependencyGate without a real TaskLifecycle."""
    def __init__(self, tasks=None):
        self.tasks = tasks or {}

    def get_state(self, task_id):
        return self.tasks.get(task_id)


# ── ArtifactGate tests ──────────────────────────────────

def test_artifact_missing():
    gate = ArtifactGate("/tmp/nonexistent_file_xyz_12345.json")
    d = gate.check()
    assert d.result == GateResult.BLOCK
    assert "missing" in d.reason


def test_artifact_empty():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        pass  # empty file
    try:
        gate = ArtifactGate(f.name)
        d = gate.check()
        assert d.result == GateResult.BLOCK
        assert "empty" in d.reason
    finally:
        os.unlink(f.name)


def test_artifact_exists_nonempty():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        f.write('{"key": "value"}')
    try:
        gate = ArtifactGate(f.name)
        d = gate.check()
        assert d.result == GateResult.PASS
    finally:
        os.unlink(f.name)


def test_artifact_with_validator_passes():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        f.write('{"valid": true}')
    try:
        def always_pass(p):
            return GateDecision(GateResult.PASS)
        gate = ArtifactGate(f.name, validator=always_pass)
        d = gate.check()
        assert d.result == GateResult.PASS
    finally:
        os.unlink(f.name)


def test_artifact_with_validator_blocks():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        f.write('{"valid": false}')
    try:
        def always_block(p):
            return GateDecision(GateResult.BLOCK, "validator said no")
        gate = ArtifactGate(f.name, validator=always_block)
        d = gate.check()
        assert d.result == GateResult.BLOCK
        assert "validator said no" in d.reason
    finally:
        os.unlink(f.name)


# ── DependencyGate tests ────────────────────────────────

def test_dependency_task_not_found():
    tl = FakeTaskLifecycle({})
    gate = DependencyGate("task-1", "done", tl)
    d = gate.check()
    assert d.result == GateResult.BLOCK
    assert "not found" in d.reason


def test_dependency_wrong_state():
    tl = FakeTaskLifecycle({"task-1": {"state": "in_progress"}})
    gate = DependencyGate("task-1", "done", tl)
    d = gate.check()
    assert d.result == GateResult.BLOCK
    assert "in_progress" in d.reason
    assert "done" in d.reason


def test_dependency_correct_state():
    tl = FakeTaskLifecycle({"task-1": {"state": "done"}})
    gate = DependencyGate("task-1", "done", tl)
    d = gate.check()
    assert d.result == GateResult.PASS


# ── TimeGate tests ──────────────────────────────────────

def test_timegate_before():
    future = int(time.time()) + 3600
    gate = TimeGate(future)
    d = gate.check()
    assert d.result == GateResult.BLOCK
    assert "too early" in d.reason


def test_timegate_after():
    past = int(time.time()) - 3600
    gate = TimeGate(past)
    d = gate.check()
    assert d.result == GateResult.PASS


# ── GateEngine.check_gates tests ────────────────────────

def test_check_gates_all_pass():
    ge = GateEngine()
    gates = [
        TimeGate(int(time.time()) - 100),
        TimeGate(int(time.time()) - 200),
    ]
    d = ge.check_gates(gates)
    assert d.result == GateResult.PASS


def test_check_gates_first_blocks():
    ge = GateEngine()
    gates = [
        TimeGate(int(time.time()) + 3600),
        TimeGate(int(time.time()) - 100),
    ]
    d = ge.check_gates(gates)
    assert d.result == GateResult.BLOCK
    assert "gate[0]" in d.reason


def test_check_gates_second_blocks():
    ge = GateEngine()
    gates = [
        TimeGate(int(time.time()) - 100),
        TimeGate(int(time.time()) + 3600),
    ]
    d = ge.check_gates(gates)
    assert d.result == GateResult.BLOCK
    assert "gate[1]" in d.reason


# ── Pipeline gate set tests ─────────────────────────────

def test_research_out_gates():
    gates = GateEngine.research_out_gates("2026-07-07")
    assert len(gates) == 1
    assert isinstance(gates[0], ArtifactGate)


def test_copy_in_gates():
    tl = FakeTaskLifecycle({"research-2026-07-07": {"state": "done"}})
    gates = GateEngine.copy_in_gates("2026-07-07", tl)
    assert len(gates) == 2
    assert isinstance(gates[0], DependencyGate)
    assert isinstance(gates[1], ArtifactGate)


def test_audit_out_gates():
    gates = GateEngine.audit_out_gates("2026-07-07")
    assert len(gates) == 1
    assert isinstance(gates[0], ArtifactGate)
    assert gates[0].validator is not None


# ── Validator tests ─────────────────────────────────────

def test_validate_json_nonempty_valid():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        f.write('{"key": "value"}')
    try:
        d = GateEngine._validate_json_nonempty(Path(f.name))
        assert d.result == GateResult.PASS
    finally:
        os.unlink(f.name)


def test_validate_json_nonempty_empty_object():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        f.write('{}')
    try:
        d = GateEngine._validate_json_nonempty(Path(f.name))
        assert d.result == GateResult.BLOCK
        assert "empty" in d.reason
    finally:
        os.unlink(f.name)


def test_validate_json_nonempty_invalid():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        f.write('not json')
    try:
        d = GateEngine._validate_json_nonempty(Path(f.name))
        assert d.result == GateResult.BLOCK
        assert "invalid JSON" in d.reason
    finally:
        os.unlink(f.name)


def test_validate_audit_approved_true():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        f.write('{"approved": true}')
    try:
        d = GateEngine._validate_audit_approved(Path(f.name))
        assert d.result == GateResult.PASS
    finally:
        os.unlink(f.name)


def test_validate_audit_approved_false():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        f.write('{"approved": false}')
    try:
        d = GateEngine._validate_audit_approved(Path(f.name))
        assert d.result == GateResult.BLOCK
        assert "not approved" in d.reason
    finally:
        os.unlink(f.name)
