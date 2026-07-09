"""Tests for the Agent Lifecycle module.

Covers:
* Agent creation with full pipeline
* Auto-assignment of ports
* Destroy (existing and unknown agents)
* List agents
* Health check (healthy, stale, unknown)
* Restart
* Schema validation
* Edge cases
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from nucleus.modules.agent_lifecycle import (
    AgentCreateResult,
    AgentLifecycle,
    AgentSpec,
    InMemoryAgentLifecycle,
    validate_agent_spec,
    validate_create_result,
)
from nucleus.modules.port_authority import FilePortAuthority
from nucleus.modules.registry_manager import FileRegistryManager


# ── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def tmp_dirs():
    """Create temporary directories for port map and registry."""
    with tempfile.TemporaryDirectory() as tmp:
        port_map_path = os.path.join(tmp, "port_map.json")
        registry_path = os.path.join(tmp, "registry.json")
        configs_dir = os.path.join(tmp, "configs")
        os.makedirs(configs_dir, exist_ok=True)

        # Override the config path used by the fallback generator
        old_cwd = os.getcwd()
        os.chdir(tmp)

        yield {
            "port_map_path": port_map_path,
            "registry_path": registry_path,
            "configs_dir": configs_dir,
            "tmp": tmp,
        }

        os.chdir(old_cwd)


@pytest.fixture
def lifecycle(tmp_dirs):
    """Return a fresh InMemoryAgentLifecycle with isolated file paths."""
    pa = FilePortAuthority(port_map_path=tmp_dirs["port_map_path"])
    rm = FileRegistryManager(registry_path=tmp_dirs["registry_path"])
    return InMemoryAgentLifecycle(port_authority=pa, registry_manager=rm)


@pytest.fixture
def valid_spec():
    """Return a valid AgentSpec for testing."""
    return AgentSpec(
        agent_id="test-agent-1",
        display_name="Test Agent",
        role="worker",
        model="deepseek-v3",
        provider="openrouter",
    )


# ── agent creation ──────────────────────────────────────────────────────


class TestAgentCreation:
    def test_create_returns_result(self, lifecycle, valid_spec):
        result = lifecycle.create(valid_spec)
        assert isinstance(result, AgentCreateResult)
        assert result.agent_id == "test-agent-1"
        assert result.transport_port > 0
        assert result.gateway_port > 0
        assert result.config_path.endswith("test-agent-1.json")
        assert result.systemd_unit == "maestro-agent-test-agent-1.service"
        assert isinstance(result.warnings, list)

    def test_create_auto_assigns_ports(self, lifecycle, valid_spec):
        valid_spec.transport_port = None
        valid_spec.gateway_port = None
        result = lifecycle.create(valid_spec)
        assert result.transport_port >= 9000
        assert result.gateway_port >= 9100
        assert result.transport_port != result.gateway_port

    def test_create_uses_specified_ports(self, lifecycle, valid_spec):
        valid_spec.transport_port = 9500
        valid_spec.gateway_port = 9600
        result = lifecycle.create(valid_spec)
        assert result.transport_port == 9500
        assert result.gateway_port == 9600

    def test_create_registers_in_registry(self, lifecycle, valid_spec):
        lifecycle.create(valid_spec)
        record = lifecycle._registry.lookup("test-agent-1")
        assert record is not None
        assert record.agentId == "test-agent-1"
        assert record.status == "active"

    def test_create_assigns_ports_in_port_authority(self, lifecycle, valid_spec):
        lifecycle.create(valid_spec)
        assignment = lifecycle._port_authority.resolve("test-agent-1")
        assert assignment.agent_id == "test-agent-1"
        assert assignment.transport_port > 0
        assert assignment.gateway_port > 0

    def test_create_invalid_spec_raises(self, lifecycle):
        bad_spec = AgentSpec(
            agent_id="",  # empty
            display_name="",
            role="",
            model="",
            provider="",
        )
        with pytest.raises(ValueError, match="Invalid AgentSpec"):
            lifecycle.create(bad_spec)

    def test_create_multiple_agents_unique_ports(self, lifecycle):
        spec1 = AgentSpec("agent-a", "A", "worker", "m1", "p1")
        spec2 = AgentSpec("agent-b", "B", "worker", "m2", "p2")
        r1 = lifecycle.create(spec1)
        r2 = lifecycle.create(spec2)
        assert r1.transport_port != r2.transport_port
        assert r1.gateway_port != r2.gateway_port

    def test_create_stores_in_memory(self, lifecycle, valid_spec):
        lifecycle.create(valid_spec)
        agents = lifecycle.list_agents()
        assert len(agents) == 1
        assert agents[0].agent_id == "test-agent-1"


# ── destroy ─────────────────────────────────────────────────────────────


class TestDestroy:
    def test_destroy_existing_agent(self, lifecycle, valid_spec):
        lifecycle.create(valid_spec)
        result = lifecycle.destroy("test-agent-1")
        assert result is True
        assert lifecycle.list_agents() == []

    def test_destroy_unknown_agent(self, lifecycle):
        result = lifecycle.destroy("nonexistent")
        assert result is False

    def test_destroy_removes_from_registry(self, lifecycle, valid_spec):
        lifecycle.create(valid_spec)
        lifecycle.destroy("test-agent-1")
        record = lifecycle._registry.lookup("test-agent-1")
        assert record is None

    def test_destroy_twice(self, lifecycle, valid_spec):
        lifecycle.create(valid_spec)
        assert lifecycle.destroy("test-agent-1") is True
        assert lifecycle.destroy("test-agent-1") is False


# ── list_agents ─────────────────────────────────────────────────────────


class TestListAgents:
    def test_list_empty(self, lifecycle):
        assert lifecycle.list_agents() == []

    def test_list_single(self, lifecycle, valid_spec):
        lifecycle.create(valid_spec)
        agents = lifecycle.list_agents()
        assert len(agents) == 1
        assert agents[0].agent_id == "test-agent-1"
        assert agents[0].display_name == "Test Agent"

    def test_list_multiple(self, lifecycle):
        for i in range(3):
            spec = AgentSpec(f"agent-{i}", f"Agent {i}", "worker", "m", "p")
            lifecycle.create(spec)
        agents = lifecycle.list_agents()
        assert len(agents) == 3
        ids = {a.agent_id for a in agents}
        assert ids == {"agent-0", "agent-1", "agent-2"}

    def test_list_after_destroy(self, lifecycle, valid_spec):
        lifecycle.create(valid_spec)
        spec2 = AgentSpec("agent-2", "Two", "worker", "m", "p")
        lifecycle.create(spec2)
        lifecycle.destroy("test-agent-1")
        agents = lifecycle.list_agents()
        assert len(agents) == 1
        assert agents[0].agent_id == "agent-2"


# ── health_check ────────────────────────────────────────────────────────


class TestHealthCheck:
    def test_health_check_healthy(self, lifecycle, valid_spec):
        lifecycle.create(valid_spec)
        healthy, detail = lifecycle.health_check("test-agent-1")
        assert healthy is True
        assert detail == "healthy"

    def test_health_check_unknown_agent(self, lifecycle):
        healthy, detail = lifecycle.health_check("nonexistent")
        assert healthy is False
        assert "not found" in detail.lower()

    def test_health_check_stale_agent(self, lifecycle, valid_spec):
        lifecycle.create(valid_spec)
        # Manually set lastSeen to 10 minutes ago
        record = lifecycle._registry.lookup("test-agent-1")
        record.lastSeen = int((time.time() - 600) * 1000)
        lifecycle._registry._update_field("test-agent-1", "lastSeen", record.lastSeen)

        healthy, detail = lifecycle.health_check("test-agent-1")
        assert healthy is False
        assert "stale" in detail.lower()

    def test_health_check_inactive_status(self, lifecycle, valid_spec):
        lifecycle.create(valid_spec)
        lifecycle._registry.set_status("test-agent-1", "inactive")
        healthy, detail = lifecycle.health_check("test-agent-1")
        assert healthy is False
        assert "inactive" in detail.lower()


# ── restart ─────────────────────────────────────────────────────────────


class TestRestart:
    def test_restart_existing_agent(self, lifecycle, valid_spec):
        lifecycle.create(valid_spec)
        result = lifecycle.restart("test-agent-1")
        assert result is True

    def test_restart_unknown_agent(self, lifecycle):
        result = lifecycle.restart("nonexistent")
        assert result is False

    def test_restart_updates_last_seen(self, lifecycle, valid_spec):
        lifecycle.create(valid_spec)
        before = lifecycle._registry.lookup("test-agent-1").lastSeen
        time.sleep(0.01)  # ensure timestamp changes
        lifecycle.restart("test-agent-1")
        after = lifecycle._registry.lookup("test-agent-1").lastSeen
        assert after >= before


# ── schema validation ──────────────────────────────────────────────────


class TestSchemaValidation:
    def test_valid_agent_spec(self):
        errors = validate_agent_spec({
            "agent_id": "agent-1",
            "display_name": "Test",
            "role": "worker",
            "model": "gpt-4",
            "provider": "openai",
        })
        assert errors == []

    def test_valid_agent_spec_with_ports(self):
        errors = validate_agent_spec({
            "agent_id": "agent-1",
            "display_name": "Test",
            "role": "worker",
            "model": "gpt-4",
            "provider": "openai",
            "transport_port": 9000,
            "gateway_port": 9100,
        })
        assert errors == []

    def test_valid_agent_spec_ports_none(self):
        errors = validate_agent_spec({
            "agent_id": "agent-1",
            "display_name": "Test",
            "role": "worker",
            "model": "gpt-4",
            "provider": "openai",
            "transport_port": None,
            "gateway_port": None,
        })
        assert errors == []

    def test_missing_required_fields(self):
        errors = validate_agent_spec({"agent_id": "x"})
        assert len(errors) > 0

    def test_invalid_port_range(self):
        errors = validate_agent_spec({
            "agent_id": "agent-1",
            "display_name": "Test",
            "role": "worker",
            "model": "gpt-4",
            "provider": "openai",
            "transport_port": 99999,
        })
        assert any("transport_port" in e for e in errors)

    def test_negative_port(self):
        errors = validate_agent_spec({
            "agent_id": "agent-1",
            "display_name": "Test",
            "role": "worker",
            "model": "gpt-4",
            "provider": "openai",
            "gateway_port": -1,
        })
        assert any("gateway_port" in e for e in errors)

    def test_valid_create_result(self):
        errors = validate_create_result({
            "agent_id": "agent-1",
            "config_path": "/tmp/config.json",
            "transport_port": 9000,
            "gateway_port": 9100,
            "systemd_unit": "maestro-agent-agent-1.service",
            "warnings": [],
        })
        assert errors == []

    def test_create_result_missing_fields(self):
        errors = validate_create_result({"agent_id": "x"})
        assert len(errors) > 0

    def test_create_result_bad_warnings(self):
        errors = validate_create_result({
            "agent_id": "agent-1",
            "config_path": "/tmp/config.json",
            "transport_port": 9000,
            "gateway_port": 9100,
            "systemd_unit": "unit",
            "warnings": "not-a-list",
        })
        assert any("warnings" in e for e in errors)


# ── edge cases ──────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_create_duplicate_agent_id(self, lifecycle, valid_spec):
        """Creating an agent with the same ID should overwrite in memory."""
        r1 = lifecycle.create(valid_spec)
        r2 = lifecycle.create(valid_spec)
        assert r1.agent_id == r2.agent_id
        # Only one agent in list
        assert len(lifecycle.list_agents()) == 1

    def test_destroy_then_recreate(self, lifecycle, valid_spec):
        lifecycle.create(valid_spec)
        lifecycle.destroy("test-agent-1")
        # Recreate
        result = lifecycle.create(valid_spec)
        assert result.agent_id == "test-agent-1"
        assert len(lifecycle.list_agents()) == 1

    def test_health_check_after_destroy(self, lifecycle, valid_spec):
        lifecycle.create(valid_spec)
        lifecycle.destroy("test-agent-1")
        healthy, detail = lifecycle.health_check("test-agent-1")
        assert healthy is False

    def test_restart_after_destroy(self, lifecycle, valid_spec):
        lifecycle.create(valid_spec)
        lifecycle.destroy("test-agent-1")
        assert lifecycle.restart("test-agent-1") is False

    def test_create_many_agents(self, lifecycle):
        """Create 20 agents and verify all are listed."""
        for i in range(20):
            spec = AgentSpec(f"agent-{i}", f"Agent {i}", "worker", "m", "p")
            lifecycle.create(spec)
        assert len(lifecycle.list_agents()) == 20

    def test_agent_spec_defaults(self):
        """AgentSpec ports default to None."""
        spec = AgentSpec("id", "name", "role", "model", "provider")
        assert spec.transport_port is None
        assert spec.gateway_port is None

    def test_create_result_warnings_default(self):
        """AgentCreateResult warnings default to empty list."""
        result = AgentCreateResult(
            agent_id="a",
            config_path="/tmp/c.json",
            transport_port=9000,
            gateway_port=9100,
            systemd_unit="unit",
        )
        assert result.warnings == []
