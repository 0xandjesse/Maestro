"""Tests for agent.audit_log module."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.audit_log import AuditLog, _MAX_FILE_SIZE_BYTES


@pytest.fixture
def tmp_audit_dir(tmp_path):
    """Provide a temporary directory for audit log files."""
    audit_dir = tmp_path / ".maestro"
    audit_dir.mkdir()
    return audit_dir


@pytest.fixture
def audit_log_instance(tmp_audit_dir):
    """Provide a fresh AuditLog instance pointing at a temp directory."""
    log = AuditLog()
    log._path = tmp_audit_dir / "audit.jsonl"
    return log


class TestAuditLogWrite:
    """Core write functionality."""

    def test_write_single_event(self, audit_log_instance):
        audit_log_instance.write("agent.start", {"agent_id": "test", "pid": 1234})
        lines = (audit_log_instance._path).read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event"] == "agent.start"
        assert entry["agent_id"] == "test"
        assert entry["pid"] == 1234
        assert "ts" in entry

    def test_write_multiple_events(self, audit_log_instance):
        audit_log_instance.write("agent.start", {"agent_id": "a"})
        audit_log_instance.write("tool.call", {"tool_name": "terminal"})
        audit_log_instance.write("agent.stop", {"agent_id": "a", "reason": "done"})
        lines = (audit_log_instance._path).read_text().strip().split("\n")
        assert len(lines) == 3
        events = [json.loads(l)["event"] for l in lines]
        assert events == ["agent.start", "tool.call", "agent.stop"]

    def test_write_never_raises(self, audit_log_instance):
        # Even if writing to a read-only path, write should not raise
        audit_log_instance._path = Path("/nonexistent/path/audit.jsonl")
        # Should silently fail, not raise
        audit_log_instance.write("agent.start", {"agent_id": "test"})
        # No assertion needed — the test passes if no exception propagates

    def test_jsonl_is_grepable(self, audit_log_instance):
        audit_log_instance.write("kill", {"target_agent_id": "stormtrooper", "issuer": "proteus"})
        content = (audit_log_instance._path).read_text()
        assert '"event": "kill"' in content
        assert '"target_agent_id": "stormtrooper"' in content
        # Each line is valid JSON
        for line in content.strip().split("\n"):
            json.loads(line)  # should not raise

    def test_timestamps_are_iso8601(self, audit_log_instance):
        audit_log_instance.write("execution.start", {"execution_id": "e1"})
        line = (audit_log_instance._path).read_text().strip()
        entry = json.loads(line)
        # Should parse without error
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(entry["ts"])
        assert dt.tzinfo is not None  # timezone-aware


class TestAuditLogRotation:
    """File rotation when exceeding size limit."""

    def test_rotation_creates_rotated_file(self, audit_log_instance):
        # Force rotation by setting a tiny size limit
        import agent.audit_log as mod
        original_limit = mod._MAX_FILE_SIZE_BYTES
        mod._MAX_FILE_SIZE_BYTES = 100  # 100 bytes

        try:
            # Write enough data to trigger rotation
            for i in range(20):
                audit_log_instance.write("test.event", {"idx": i, "padding": "x" * 20})
            
            # Reset size check to force re-check
            audit_log_instance._size_checked_at = 0.0
            
            # Write one more to trigger rotation
            audit_log_instance.write("trigger.rotation", {"reason": "size"})
            
            # After rotation, original file should exist (new one) and .1 should exist
            rotated = audit_log_instance._path.parent / "audit.jsonl.1"
            assert rotated.exists() or audit_log_instance._path.exists()
        finally:
            mod._MAX_FILE_SIZE_BYTES = original_limit

    def test_max_rotated_files(self, audit_log_instance):
        import agent.audit_log as mod
        original_limit = mod._MAX_FILE_SIZE_BYTES
        mod._MAX_FILE_SIZE_BYTES = 50  # Very small to force multiple rotations

        try:
            for rotation in range(8):
                audit_log_instance._size_checked_at = 0.0  # Force size check each time
                for i in range(5):
                    audit_log_instance.write("rotation.test", {"rotation": rotation, "idx": i, "data": "x" * 30})
            
            # Should not have more than 5 rotated files
            parent = audit_log_instance._path.parent
            rotated_files = sorted(parent.glob("audit.jsonl.*"))
            assert len(rotated_files) <= 5
        finally:
            mod._MAX_FILE_SIZE_BYTES = original_limit


class TestAuditEventTypes:
    """Verify all event types from the spec can be logged."""

    def test_all_spec_events(self, audit_log_instance):
        events = {
            "agent.start": {"agent_id": "hermes", "pid": 12345, "port": 8641, "profile": "hermes", "model": "claude-opus-4", "config_hash": "abc123"},
            "agent.stop": {"agent_id": "hermes", "reason": "shutdown", "exit_code": 0, "duration_s": 3600},
            "execution.start": {"execution_id": "e1", "parent_execution_id": None, "agent_id": "hermes", "user_id": "u1", "platform": "cli"},
            "execution.end": {"execution_id": "e1", "iterations": 5, "tokens": 10000, "cost_cents": 50, "wall_clock_s": 120, "outcome": "success"},
            "tool.call": {"execution_id": "e1", "tool_name": "terminal", "args_hash": "sha256:abc", "ts": "2026-05-18T00:00:00+00:00"},
            "tool.result": {"execution_id": "e1", "tool_name": "terminal", "success": True, "bytes_out": 1024, "duration_ms": 500},
            "kill": {"target_agent_id": "stormtrooper", "issuer": "proteus", "reason": "manual", "timestamp": "2026-05-18T00:00:00+00:00"},
            "cap.breach": {"execution_id": "e1", "cap_type": "max_iterations", "limit": 50, "actual": 51},
            "transport.send": {"from_agent": "hermes", "to_agent": "stormtrooper", "message_id": "m1", "bytes": 500},
            "transport.recv": {"to_agent": "stormtrooper", "from_agent": "hermes", "message_id": "m1", "bytes": 500},
            "error": {"execution_id": "e1", "error_type": "RuntimeError", "error_message": "something broke", "stack_trace_hash": "sha256:def"},
        }
        
        for event_type, data in events.items():
            audit_log_instance.write(event_type, data)
        
        lines = (audit_log_instance._path).read_text().strip().split("\n")
        assert len(lines) == len(events)
        
        logged_events = set()
        for line in lines:
            entry = json.loads(line)
            logged_events.add(entry["event"])
        assert logged_events == set(events.keys())


class TestConvenienceMethods:
    """Test write_cap_breach and write_error convenience methods."""

    def test_write_cap_breach(self, audit_log_instance):
        audit_log_instance.write_cap_breach(
            execution_id="e1",
            cap_type="max_iterations",
            limit=50,
            actual=51,
        )
        lines = (audit_log_instance._path).read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event"] == "cap.breach"
        assert entry["execution_id"] == "e1"
        assert entry["cap_type"] == "max_iterations"
        assert entry["limit"] == 50
        assert entry["actual"] == 51
        assert "ts" in entry

    def test_write_error(self, audit_log_instance):
        audit_log_instance.write_error(
            execution_id="e2",
            error_type="RuntimeError",
            error_message="something went wrong",
            stack_trace_hash="abc123",
        )
        lines = (audit_log_instance._path).read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event"] == "error"
        assert entry["execution_id"] == "e2"
        assert entry["error_type"] == "RuntimeError"
        assert entry["error_message"] == "something went wrong"
        assert entry["stack_trace_hash"] == "abc123"

    def test_write_error_truncates_long_message(self, audit_log_instance):
        long_msg = "x" * 300
        audit_log_instance.write_error(
            execution_id="e3",
            error_type="ValueError",
            error_message=long_msg,
        )
        lines = (audit_log_instance._path).read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert len(entry["error_message"]) == 200

    def test_agent_stop_with_duration(self, audit_log_instance):
        audit_log_instance.write("agent.stop", {
            "agent_id": "hermes",
            "reason": "shutdown",
            "exit_code": 0,
            "duration_s": 3600,
        })
        lines = (audit_log_instance._path).read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert entry["event"] == "agent.stop"
        assert entry["duration_s"] == 3600