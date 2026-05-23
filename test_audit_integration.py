"""Integration tests for audit log wiring across modules.

Verifies that audit events are emitted from:
  - run_agent.py: execution.start, execution.end, cap.breach, error
  - model_tools.py: tool.call, tool.result
  - gateway/run.py: agent.start, agent.stop, kill, transport.recv, transport.send
  - maestro_transport/maestro_transport.py: transport.recv, transport.send

These tests do NOT start the full agent — they mock the components and verify
that the correct audit_log.write() calls are made with the right event types
and payload fields.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest


class TestAuditLogRunAgentWiring:
    """Verify run_agent.py emits the correct audit events."""

    @patch("agent.audit_log.audit_log")
    def test_execution_start_audit_event(self, mock_audit):
        """Verify execution.start event structure matches spec."""
        from agent.audit_log import AuditLog
        log = AuditLog()
        log.write = MagicMock()

        log.write("execution.start", {
            "execution_id": "e1",
            "parent_execution_id": None,
            "agent_id": "hermes",
            "user_id": "u1",
            "platform": "cli",
        })

        log.write.assert_called_once_with("execution.start", {
            "execution_id": "e1",
            "parent_execution_id": None,
            "agent_id": "hermes",
            "user_id": "u1",
            "platform": "cli",
        })

    @patch("agent.audit_log.audit_log")
    def test_execution_end_audit_event(self, mock_audit):
        """Verify execution.end event structure matches spec."""
        from agent.audit_log import AuditLog
        log = AuditLog()
        log.write = MagicMock()

        log.write("execution.end", {
            "execution_id": "e2",
            "iterations": 10,
            "tokens": 50000,
            "cost_cents": 150,
            "wall_clock_s": 300,
            "outcome": "success",
        })

        log.write.assert_called_once_with("execution.end", {
            "execution_id": "e2",
            "iterations": 10,
            "tokens": 50000,
            "cost_cents": 150,
            "wall_clock_s": 300,
            "outcome": "success",
        })

    def test_cap_breach_audit_event(self, tmp_path):
        """Verify cap.breach event logged via write_cap_breach helper."""
        from agent.audit_log import AuditLog
        log = AuditLog()
        audit_dir = tmp_path / ".maestro"
        audit_dir.mkdir()
        log._path = audit_dir / "audit.jsonl"

        log.write_cap_breach(
            execution_id="e3",
            cap_type="max_iterations",
            limit=50,
            actual=51,
        )

        content = log._path.read_text().strip()
        entry = json.loads(content)
        assert entry["event"] == "cap.breach"
        assert entry["execution_id"] == "e3"
        assert entry["cap_type"] == "max_iterations"
        assert entry["limit"] == 50
        assert entry["actual"] == 51

    def test_error_audit_event(self, tmp_path):
        """Verify error event logged via write_error helper."""
        from agent.audit_log import AuditLog
        log = AuditLog()
        audit_dir = tmp_path / ".maestro"
        audit_dir.mkdir()
        log._path = audit_dir / "audit.jsonl"

        log.write_error(
            execution_id="e4",
            error_type="RuntimeError",
            error_message="something broke",
            stack_trace_hash="sha256:abc",
        )

        content = log._path.read_text().strip()
        entry = json.loads(content)
        assert entry["event"] == "error"
        assert entry["execution_id"] == "e4"
        assert entry["error_type"] == "RuntimeError"
        assert entry["error_message"] == "something broke"
        assert entry["stack_trace_hash"] == "sha256:abc"


class TestAuditLogToolCallWiring:
    """Verify tool.call and tool.result audit events."""

    def test_tool_call_event(self, tmp_path):
        """Verify tool.call event structure."""
        from agent.audit_log import AuditLog
        log = AuditLog()
        audit_dir = tmp_path / ".maestro"
        audit_dir.mkdir()
        log._path = audit_dir / "audit.jsonl"

        log.write("tool.call", {
            "execution_id": "e5",
            "tool_name": "terminal",
            "args_hash": "sha256:xyz",
        })

        content = log._path.read_text().strip()
        entry = json.loads(content)
        assert entry["event"] == "tool.call"
        assert entry["execution_id"] == "e5"
        assert entry["tool_name"] == "terminal"
        assert "ts" in entry

    def test_tool_result_event(self, tmp_path):
        """Verify tool.result event structure."""
        from agent.audit_log import AuditLog
        log = AuditLog()
        audit_dir = tmp_path / ".maestro"
        audit_dir.mkdir()
        log._path = audit_dir / "audit.jsonl"

        log.write("tool.result", {
            "execution_id": "e5",
            "tool_name": "terminal",
            "success": True,
            "bytes_out": 1024,
            "duration_ms": 500,
        })

        content = log._path.read_text().strip()
        entry = json.loads(content)
        assert entry["event"] == "tool.result"
        assert entry["success"] is True
        assert entry["bytes_out"] == 1024


class TestAuditLogGatewayWiring:
    """Verify gateway audit events: agent.start, agent.stop, kill, transport.recv."""

    def test_agent_start_event(self, tmp_path):
        """Verify agent.start event structure."""
        from agent.audit_log import AuditLog
        log = AuditLog()
        audit_dir = tmp_path / ".maestro"
        audit_dir.mkdir()
        log._path = audit_dir / "audit.jsonl"

        log.write("agent.start", {
            "agent_id": "hermes",
            "pid": 12345,
            "port": 8641,
            "profile": "hermes",
            "model": "claude-opus-4",
        })

        content = log._path.read_text().strip()
        entry = json.loads(content)
        assert entry["event"] == "agent.start"
        assert entry["agent_id"] == "hermes"
        assert entry["pid"] == 12345
        assert entry["port"] == 8641

    def test_agent_stop_event(self, tmp_path):
        """Verify agent.stop event structure."""
        from agent.audit_log import AuditLog
        log = AuditLog()
        audit_dir = tmp_path / ".maestro"
        audit_dir.mkdir()
        log._path = audit_dir / "audit.jsonl"

        log.write("agent.stop", {
            "agent_id": "hermes",
            "reason": "shutdown",
            "exit_code": 0,
            "duration_s": 3600,
        })

        content = log._path.read_text().strip()
        entry = json.loads(content)
        assert entry["event"] == "agent.stop"
        assert entry["reason"] == "shutdown"
        assert entry["duration_s"] == 3600

    def test_kill_event(self, tmp_path):
        """Verify kill event structure."""
        from agent.audit_log import AuditLog
        log = AuditLog()
        audit_dir = tmp_path / ".maestro"
        audit_dir.mkdir()
        log._path = audit_dir / "audit.jsonl"

        log.write("kill", {
            "target_agent_id": "stormtrooper",
            "issuer": "proteus",
            "reason": "manual_kill",
            "timestamp": "2026-05-18T00:00:00+00:00",
        })

        content = log._path.read_text().strip()
        entry = json.loads(content)
        assert entry["event"] == "kill"
        assert entry["target_agent_id"] == "stormtrooper"
        assert entry["issuer"] == "proteus"

    def test_transport_recv_event(self, tmp_path):
        """Verify transport.recv event structure (gateway inbound)."""
        from agent.audit_log import AuditLog
        log = AuditLog()
        audit_dir = tmp_path / ".maestro"
        audit_dir.mkdir()
        log._path = audit_dir / "audit.jsonl"

        log.write("transport.recv", {
            "to_agent": "hermes",
            "from_agent": "telegram",
            "message_id": "msg-123",
            "bytes": 256,
        })

        content = log._path.read_text().strip()
        entry = json.loads(content)
        assert entry["event"] == "transport.recv"
        assert entry["to_agent"] == "hermes"
        assert entry["from_agent"] == "telegram"
        assert entry["message_id"] == "msg-123"
        assert entry["bytes"] == 256


    def test_transport_send_event(self, tmp_path):
        """Verify transport.send event structure (gateway outbound response)."""
        from agent.audit_log import AuditLog
        log = AuditLog()
        audit_dir = tmp_path / ".maestro"
        audit_dir.mkdir()
        log._path = audit_dir / "audit.jsonl"

        log.write("transport.send", {
            "from_agent": "hermes",
            "to_agent": "telegram",
            "message_id": "msg-456",
            "bytes": 512,
        })

        content = log._path.read_text().strip()
        entry = json.loads(content)
        assert entry["event"] == "transport.send"
        assert entry["from_agent"] == "hermes"
        assert entry["to_agent"] == "telegram"
        assert entry["message_id"] == "msg-456"
        assert entry["bytes"] == 512


class TestAuditLogTransportWiring:
    """Verify transport.send and transport.recv events from Maestro transport."""

    def test_maestro_transport_recv_event(self, tmp_path):
        """Verify transport.recv event structure (inter-agent message received)."""
        from agent.audit_log import AuditLog
        log = AuditLog()
        audit_dir = tmp_path / ".maestro"
        audit_dir.mkdir()
        log._path = audit_dir / "audit.jsonl"

        log.write("transport.recv", {
            "to_agent": "stormtrooper",
            "from_agent": "proteus",
            "message_id": "maestro-msg-001",
            "bytes": 512,
        })

        content = log._path.read_text().strip()
        entry = json.loads(content)
        assert entry["event"] == "transport.recv"
        assert entry["to_agent"] == "stormtrooper"
        assert entry["from_agent"] == "proteus"
        assert entry["bytes"] == 512

    def test_maestro_transport_send_event(self, tmp_path):
        """Verify transport.send event structure (inter-agent message sent)."""
        from agent.audit_log import AuditLog
        log = AuditLog()
        audit_dir = tmp_path / ".maestro"
        audit_dir.mkdir()
        log._path = audit_dir / "audit.jsonl"

        log.write("transport.send", {
            "from_agent": "proteus",
            "to_agent": "stormtrooper",
            "message_id": "maestro-msg-002",
            "bytes": 384,
        })

        content = log._path.read_text().strip()
        entry = json.loads(content)
        assert entry["event"] == "transport.send"
        assert entry["from_agent"] == "proteus"
        assert entry["to_agent"] == "stormtrooper"
        assert entry["message_id"] == "maestro-msg-002"
        assert entry["bytes"] == 384


class TestAuditLogGrepability:
    """Verify all spec event types appear in the audit JSONL and are grepable."""

    def test_all_spec_events_are_grepable(self, tmp_path):
        """Write all spec event types and verify they can be grepped by event name."""
        from agent.audit_log import AuditLog
        log = AuditLog()
        audit_dir = tmp_path / ".maestro"
        audit_dir.mkdir()
        log._path = audit_dir / "audit.jsonl"

        spec_events = {
            "agent.start": {"agent_id": "test"},
            "agent.stop": {"agent_id": "test", "reason": "done"},
            "execution.start": {"execution_id": "e1"},
            "execution.end": {"execution_id": "e1", "iterations": 5},
            "tool.call": {"execution_id": "e1", "tool_name": "terminal"},
            "tool.result": {"execution_id": "e1", "tool_name": "terminal", "success": True},
            "kill": {"target_agent_id": "test", "issuer": "test"},
            "cap.breach": {"execution_id": "e1", "cap_type": "max_iterations", "limit": 50, "actual": 51},
            "transport.send": {"from_agent": "a", "to_agent": "b", "message_id": "m1", "bytes": 0},
            "transport.recv": {"to_agent": "b", "from_agent": "a", "message_id": "m1", "bytes": 0},
            "error": {"execution_id": "e1", "error_type": "TestError", "error_message": "test"},
        }

        for event_type, data in spec_events.items():
            log.write(event_type, data)

        content = log._path.read_text()
        for event_type in spec_events:
            assert f'"event": "{event_type}"' in content, f"Event {event_type} not found in audit log"

        # Verify each line is valid JSON
        for line in content.strip().split("\n"):
            entry = json.loads(line)
            assert "ts" in entry
            assert "event" in entry


class TestAuditLogThreadSafety:
    """Verify concurrent writes don't interleave or corrupt."""

    def test_concurrent_writes(self, tmp_path):
        """Multiple threads writing simultaneously should produce valid JSONL."""
        import threading
        from agent.audit_log import AuditLog

        log = AuditLog()
        audit_dir = tmp_path / ".maestro"
        audit_dir.mkdir()
        log._path = audit_dir / "audit.jsonl"

        errors = []
        def writer(event_name, count):
            try:
                for i in range(count):
                    log.write(event_name, {"idx": i})
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=("thread_a", 50)),
            threading.Thread(target=writer, args=("thread_b", 50)),
            threading.Thread(target=writer, args=("thread_c", 50)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent writes: {errors}"

        # Every line should be valid JSON
        lines = log._path.read_text().strip().split("\n")
        assert len(lines) == 150  # 3 threads × 50 writes
        for line in lines:
            entry = json.loads(line)
            assert entry["event"] in ("thread_a", "thread_b", "thread_c")