# nucleus/modules/config_generator/test_generator.py
"""Unit tests for Config Generator (Module 9)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

# Ensure the config_generator package is importable
import sys

_MODULE_DIR = str(Path(__file__).resolve().parent.parent)
if _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)

from config_generator.interface import AgentConfig, ConfigTemplate
from config_generator.generator import FileConfigGenerator
from config_generator.schema import validate_config


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def temp_port_map():
    """Create a temporary port map with a few agents registered."""
    data = {
        "version": "1.0.0",
        "last_updated": "2026-06-30T00:00:00Z",
        "agents": {
            "proteus": {"transport_port": 3846, "gateway_port": 4846},
            "cactus-jack": {"transport_port": 3852, "gateway_port": 4852},
            "songbird": {"transport_port": 3842, "gateway_port": 4842},
            "lexicon": {"transport_port": 3843, "gateway_port": 4843},
        },
        "bridge": {"port": 8644},
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(data, f)
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture
def temp_registry():
    """Create a temporary registry with a few agents."""
    data = [
        {
            "agentId": "proteus",
            "webhookEndpoint": "http://127.0.0.1:3846/message",
            "capabilities": [],
            "registeredAt": 1782837600352,
            "lastSeen": 1782837600352,
        },
        {
            "agentId": "cactus-jack",
            "webhookEndpoint": "http://127.0.0.1:3852/message",
            "capabilities": [],
            "registeredAt": 1782837600352,
            "lastSeen": 1782837600352,
        },
        {
            "agentId": "songbird",
            "webhookEndpoint": "http://127.0.0.1:3842/message",
            "capabilities": [],
            "registeredAt": 1782837600352,
            "lastSeen": 1782837600352,
        },
        {
            "agentId": "lexicon",
            "webhookEndpoint": "http://127.0.0.1:3843/message",
            "capabilities": [],
            "registeredAt": 1782837600352,
            "lastSeen": 1782837600352,
        },
    ]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(data, f)
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture
def temp_configs_dir():
    """Create a temporary directory for config output."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def generator(temp_port_map, temp_registry, temp_configs_dir):
    """Create a FileConfigGenerator backed by temp files."""
    return FileConfigGenerator(
        port_map_path=temp_port_map,
        registry_path=temp_registry,
        configs_dir=temp_configs_dir,
    )


# ── helper ──────────────────────────────────────────────────────────────


def _make_valid_config(**overrides) -> AgentConfig:
    """Build a minimally valid AgentConfig for validation tests."""
    defaults = {
        "agentId": "test-agent",
        "port": 5000,
        "hermesApiUrl": "http://127.0.0.1:3844",
        "hermesApiKey": "maestro-local-dev",
        "conversation": "test-conversation",
        "registryPath": "~/.maestro/registry.json",
        "version": "3.2",
        "knownPeers": {"peer1": "http://127.0.0.1:5001/message"},
        "surfaceToGateway": True,
        "gatewayBridgeUrl": "http://127.0.0.1:8644/maestro/notify",
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


# ── ConfigTemplate tests ────────────────────────────────────────────────


class TestConfigTemplate:
    """Template defaults are correct."""

    def test_default_version(self):
        t = ConfigTemplate()
        assert t.version == "3.2"

    def test_default_api_key(self):
        t = ConfigTemplate()
        assert t.hermesApiKey == "maestro-local-dev"

    def test_default_registry_path(self):
        t = ConfigTemplate()
        assert t.registryPath == "~/.maestro/registry.json"

    def test_default_surface_to_gateway(self):
        t = ConfigTemplate()
        assert t.surfaceToGateway is True

    def test_default_gateway_bridge_url(self):
        t = ConfigTemplate()
        assert t.gatewayBridgeUrl == "http://127.0.0.1:8644/maestro/notify"


# ── generate() tests ────────────────────────────────────────────────────


class TestGenerate:
    """generate() creates valid AgentConfig with correct defaults."""

    def test_generate_returns_agent_config(self, generator):
        config = generator.generate("proteus")
        assert isinstance(config, AgentConfig)

    def test_generate_sets_agent_id(self, generator):
        config = generator.generate("proteus")
        assert config.agentId == "proteus"

    def test_generate_resolves_port_from_port_authority(self, generator):
        config = generator.generate("proteus")
        assert config.port == 3846

    def test_generate_uses_template_defaults(self, generator):
        config = generator.generate("proteus")
        assert config.version == "3.2"
        assert config.hermesApiKey == "maestro-local-dev"
        assert config.registryPath == "~/.maestro/registry.json"
        assert config.surfaceToGateway is True
        assert config.gatewayBridgeUrl == "http://127.0.0.1:8644/maestro/notify"

    def test_generate_builds_known_peers(self, generator):
        config = generator.generate("proteus")
        # proteus should NOT be in its own knownPeers
        assert "proteus" not in config.knownPeers
        # Other agents should be present
        assert "cactus-jack" in config.knownPeers
        assert "songbird" in config.knownPeers
        assert "lexicon" in config.knownPeers
        # Values should be webhook endpoints
        assert config.knownPeers["cactus-jack"] == (
            "http://127.0.0.1:3852/message"
        )

    def test_generate_unknown_agent_raises_keyerror(self, generator):
        with pytest.raises(KeyError, match="not found in port map"):
            generator.generate("nonexistent-agent")

    def test_generate_applies_overrides(self, generator):
        config = generator.generate(
            "proteus",
            overrides={
                "version": "4.0",
                "hermesApiKey": "custom-key",
                "conversation": "my-convo",
                "surfaceToGateway": False,
            },
        )
        assert config.version == "4.0"
        assert config.hermesApiKey == "custom-key"
        assert config.conversation == "my-convo"
        assert config.surfaceToGateway is False

    def test_generate_overrides_dont_affect_port(self, generator):
        config = generator.generate(
            "proteus", overrides={"port": 9999}
        )
        # Port comes from Port Authority, not overrides
        assert config.port == 3846

    def test_generate_overrides_dont_affect_known_peers(self, generator):
        config = generator.generate(
            "proteus",
            overrides={"knownPeers": {"fake": "http://fake"}},
        )
        # knownPeers comes from registry, not overrides
        assert "cactus-jack" in config.knownPeers

    def test_generate_different_agent_different_port(self, generator):
        config = generator.generate("songbird")
        assert config.port == 3842

    def test_generate_different_agent_different_peers(self, generator):
        config = generator.generate("cactus-jack")
        # cactus-jack should NOT be in its own knownPeers
        assert "cactus-jack" not in config.knownPeers
        assert "proteus" in config.knownPeers


# ── validate() tests ────────────────────────────────────────────────────


class TestValidate:
    """validate() catches issues correctly."""

    def test_valid_config_returns_empty_list(self, generator):
        config = _make_valid_config()
        issues = generator.validate(config)
        assert issues == []

    def test_missing_agent_id(self, generator):
        config = _make_valid_config(agentId="")
        issues = generator.validate(config)
        assert any("agentId" in i for i in issues)

    def test_missing_port(self, generator):
        config = _make_valid_config(port=None)
        issues = generator.validate(config)
        assert any("port" in i for i in issues)

    def test_port_below_range(self, generator):
        config = _make_valid_config(port=80)
        issues = generator.validate(config)
        assert any("outside valid range" in i for i in issues)

    def test_port_above_range(self, generator):
        config = _make_valid_config(port=99999)
        issues = generator.validate(config)
        assert any("outside valid range" in i for i in issues)

    def test_port_zero(self, generator):
        config = _make_valid_config(port=0)
        issues = generator.validate(config)
        assert any("outside valid range" in i for i in issues)

    def test_port_negative(self, generator):
        config = _make_valid_config(port=-1)
        issues = generator.validate(config)
        assert any("outside valid range" in i for i in issues)

    def test_port_is_string(self, generator):
        config = _make_valid_config(port="not-a-number")
        issues = generator.validate(config)
        assert any("port must be an integer" in i for i in issues)

    def test_invalid_hermes_api_url(self, generator):
        config = _make_valid_config(hermesApiUrl="not-a-url")
        issues = generator.validate(config)
        assert any("hermesApiUrl" in i for i in issues)

    def test_invalid_gateway_bridge_url(self, generator):
        config = _make_valid_config(gatewayBridgeUrl="ftp://bad")
        issues = generator.validate(config)
        assert any("gatewayBridgeUrl" in i for i in issues)

    def test_missing_conversation(self, generator):
        config = _make_valid_config(conversation="")
        issues = generator.validate(config)
        assert any("conversation" in i for i in issues)

    def test_missing_hermes_api_key(self, generator):
        config = _make_valid_config(hermesApiKey="")
        issues = generator.validate(config)
        assert any("hermesApiKey" in i for i in issues)

    def test_known_peers_not_dict(self, generator):
        config = _make_valid_config(knownPeers="not-a-dict")
        issues = generator.validate(config)
        assert any("knownPeers" in i for i in issues)

    def test_surface_to_gateway_not_bool(self, generator):
        config = _make_valid_config(surfaceToGateway="yes")
        issues = generator.validate(config)
        assert any("surfaceToGateway" in i for i in issues)

    def test_multiple_issues_returned(self, generator):
        config = _make_valid_config(
            agentId="", port=0, hermesApiUrl="bad"
        )
        issues = generator.validate(config)
        assert len(issues) >= 3

    def test_standalone_validate_function(self):
        """validate_config() works without a generator instance."""
        config = _make_valid_config()
        issues = validate_config(config)
        assert issues == []


# ── write() tests ───────────────────────────────────────────────────────


class TestWrite:
    """write() creates config file with atomic write."""

    def test_write_returns_path(self, generator):
        config = generator.generate("proteus")
        path = generator.write("proteus", config)
        assert path.endswith("proteus.json")

    def test_write_creates_file(self, generator, temp_configs_dir):
        config = generator.generate("proteus")
        path = generator.write("proteus", config)
        assert os.path.exists(path)

    def test_write_content_is_valid_json(self, generator):
        config = generator.generate("proteus")
        path = generator.write("proteus", config)
        with open(path) as f:
            data = json.load(f)
        assert data["agentId"] == "proteus"
        assert data["port"] == 3846

    def test_write_includes_all_fields(self, generator):
        config = generator.generate("proteus")
        path = generator.write("proteus", config)
        with open(path) as f:
            data = json.load(f)
        expected_fields = [
            "agentId", "port", "hermesApiUrl", "hermesApiKey",
            "conversation", "registryPath", "version", "knownPeers",
            "surfaceToGateway", "gatewayBridgeUrl",
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"

    def test_write_no_temp_file_left_behind(self, generator):
        config = generator.generate("proteus")
        path = generator.write("proteus", config)
        tmp_path = path + ".tmp"
        assert not os.path.exists(tmp_path)

    def test_write_overwrites_existing(self, generator):
        config1 = generator.generate("proteus")
        generator.write("proteus", config1)

        config2 = generator.generate(
            "proteus", overrides={"version": "5.0"}
        )
        generator.write("proteus", config2)

        path = str(
            Path(generator._configs_dir) / "proteus.json"
        )
        with open(path) as f:
            data = json.load(f)
        assert data["version"] == "5.0"


# ── regenerate_all() tests ─────────────────────────────────────────────


class TestRegenerateAll:
    """regenerate_all() produces configs for all agents."""

    def test_regenerate_all_returns_dict(self, generator):
        results = generator.regenerate_all()
        assert isinstance(results, dict)

    def test_regenerate_all_includes_all_registered_agents(self, generator):
        results = generator.regenerate_all()
        # All 4 agents in the temp registry are also in the port map
        assert "proteus" in results
        assert "cactus-jack" in results
        assert "songbird" in results
        assert "lexicon" in results

    def test_regenerate_all_values_are_agent_configs(self, generator):
        results = generator.regenerate_all()
        for config in results.values():
            assert isinstance(config, AgentConfig)

    def test_regenerate_all_skips_agents_not_in_port_map(
        self, temp_configs_dir, temp_port_map
    ):
        """Agents in registry but not in port map are skipped."""
        # Create a registry with an extra agent not in port map
        registry_data = [
            {
                "agentId": "proteus",
                "webhookEndpoint": "http://127.0.0.1:3846/message",
            },
            {
                "agentId": "ghost-agent",
                "webhookEndpoint": "http://127.0.0.1:9999/message",
            },
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(registry_data, f)
            reg_path = f.name

        try:
            gen = FileConfigGenerator(
                port_map_path=temp_port_map,
                registry_path=reg_path,
                configs_dir=temp_configs_dir,
            )
            results = gen.regenerate_all()
            assert "proteus" in results
            assert "ghost-agent" not in results
        finally:
            os.unlink(reg_path)


# ── edge case tests ─────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_registry(self, temp_port_map, temp_configs_dir):
        """Empty registry produces empty results."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump([], f)
            reg_path = f.name

        try:
            gen = FileConfigGenerator(
                port_map_path=temp_port_map,
                registry_path=reg_path,
                configs_dir=temp_configs_dir,
            )
            results = gen.regenerate_all()
            assert results == {}
        finally:
            os.unlink(reg_path)

    def test_missing_registry_file(self, temp_port_map, temp_configs_dir):
        """Missing registry file produces empty results."""
        gen = FileConfigGenerator(
            port_map_path=temp_port_map,
            registry_path="/tmp/nonexistent-registry-99999.json",
            configs_dir=temp_configs_dir,
        )
        results = gen.regenerate_all()
        assert results == {}

    def test_agent_with_no_peers(self, temp_port_map, temp_configs_dir):
        """Agent that is the only one in registry has empty knownPeers."""
        registry_data = [
            {
                "agentId": "proteus",
                "webhookEndpoint": "http://127.0.0.1:3846/message",
            },
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(registry_data, f)
            reg_path = f.name

        try:
            gen = FileConfigGenerator(
                port_map_path=temp_port_map,
                registry_path=reg_path,
                configs_dir=temp_configs_dir,
            )
            config = gen.generate("proteus")
            assert config.knownPeers == {}
        finally:
            os.unlink(reg_path)

    def test_agent_with_no_webhook_endpoint(self, temp_port_map, temp_configs_dir):
        """Agent without webhookEndpoint is excluded from knownPeers."""
        registry_data = [
            {
                "agentId": "proteus",
                "webhookEndpoint": "http://127.0.0.1:3846/message",
            },
            {
                "agentId": "cactus-jack",
                "webhookEndpoint": "",
            },
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(registry_data, f)
            reg_path = f.name

        try:
            gen = FileConfigGenerator(
                port_map_path=temp_port_map,
                registry_path=reg_path,
                configs_dir=temp_configs_dir,
            )
            config = gen.generate("proteus")
            # cactus-jack has no webhook endpoint, so it should be excluded
            assert "cactus-jack" not in config.knownPeers
        finally:
            os.unlink(reg_path)

    def test_override_dm_policy(self, generator):
        config = generator.generate(
            "proteus",
            overrides={"dm_policy": {"allow": ["songbird"]}},
        )
        assert config.dm_policy == {"allow": ["songbird"]}

    def test_override_registry_signer_public_key(self, generator):
        config = generator.generate(
            "proteus",
            overrides={
                "registry_signer_public_key": "abc123def456"
            },
        )
        assert config.registry_signer_public_key == "abc123def456"

    def test_validate_accepts_https_urls(self, generator):
        config = _make_valid_config(
            hermesApiUrl="https://api.example.com",
            gatewayBridgeUrl="https://bridge.example.com/notify",
        )
        issues = generator.validate(config)
        assert issues == []

    def test_port_at_lower_boundary(self, generator):
        config = _make_valid_config(port=1024)
        issues = generator.validate(config)
        assert issues == []

    def test_port_at_upper_boundary(self, generator):
        config = _make_valid_config(port=65535)
        issues = generator.validate(config)
        assert issues == []

    def test_port_just_below_boundary(self, generator):
        config = _make_valid_config(port=1023)
        issues = generator.validate(config)
        assert any("outside valid range" in i for i in issues)

    def test_port_just_above_boundary(self, generator):
        config = _make_valid_config(port=65536)
        issues = generator.validate(config)
        assert any("outside valid range" in i for i in issues)
