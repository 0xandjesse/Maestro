"""Tests for the Visibility Registry module.

Covers:
* Default generation for any agent
* check() returns correct visibility for inbound/outbound
* set_mode() updates and persists
* Direction filtering (inbound vs outbound, "off" mode)
* Schema validation
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from nucleus.modules.visibility_registry import (
    FileVisibilityRegistry,
    VisibilityConfig,
    validate_config,
    validate_registry,
)


# ── fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def tmp_registry_path():
    """Create a temp file path for an isolated visibility registry."""
    fd, path = tempfile.mkstemp(suffix=".json", prefix="test_visibility_")
    os.close(fd)
    yield path
    # Cleanup
    for suffix in ("", ".tmp"):
        p = Path(path + suffix) if suffix else Path(path)
        if p.exists():
            p.unlink(missing_ok=True)


@pytest.fixture
def registry(tmp_registry_path):
    """Return a FileVisibilityRegistry pointed at a temp file."""
    return FileVisibilityRegistry(tmp_registry_path)


# ── default generation ─────────────────────────────────────────────────

class TestDefaultGeneration:
    def test_generate_for_new_agent(self, registry):
        config = registry.generate_for_agent("cee-lo")
        assert config.agent_id == "cee-lo"
        assert config.display_mode == "on"
        assert config.surface_inbound is True
        assert config.surface_outbound is True
        assert config.surface_system is False
        assert config.generated_at > 0

    def test_generate_is_idempotent(self, registry):
        c1 = registry.generate_for_agent("cee-lo")
        c2 = registry.generate_for_agent("cee-lo")
        assert c1.agent_id == c2.agent_id
        assert c1.display_mode == c2.display_mode
        # generated_at should be the same (no overwrite on re-fetch)
        assert c1.generated_at == c2.generated_at

    def test_generate_multiple_agents(self, registry):
        for agent_id in ("cee-lo", "cactus-jack", "proteus"):
            config = registry.generate_for_agent(agent_id)
            assert config.agent_id == agent_id
            assert config.display_mode == "on"

        all_configs = registry.list_all()
        assert len(all_configs) == 3
        ids = {c.agent_id for c in all_configs}
        assert ids == {"cee-lo", "cactus-jack", "proteus"}


# ── check() — direction filtering ──────────────────────────────────────

class TestCheck:
    def test_check_inbound_default(self, registry):
        registry.generate_for_agent("cee-lo")
        visible, mode = registry.check("cee-lo", "inbound")
        assert visible is True
        assert mode == "on"

    def test_check_outbound_default(self, registry):
        registry.generate_for_agent("cee-lo")
        visible, mode = registry.check("cee-lo", "outbound")
        assert visible is True
        assert mode == "on"

    def test_check_auto_generates(self, registry):
        """check() should auto-generate a default config if none exists."""
        visible, mode = registry.check("new-agent", "inbound")
        assert visible is True
        assert mode == "on"
        # Verify it was persisted
        all_configs = registry.list_all()
        assert any(c.agent_id == "new-agent" for c in all_configs)

    def test_check_invalid_direction(self, registry):
        with pytest.raises(ValueError, match="direction"):
            registry.check("cee-lo", "sideways")

    def test_check_off_mode(self, registry):
        registry.generate_for_agent("cee-lo")
        registry.set_mode("cee-lo", "off")
        visible_in, mode_in = registry.check("cee-lo", "inbound")
        visible_out, mode_out = registry.check("cee-lo", "outbound")
        assert visible_in is False
        assert mode_in == "off"
        assert visible_out is False
        assert mode_out == "off"

    def test_check_inbound_only(self, registry):
        """When surface_inbound is False, inbound check returns False."""
        config = registry.generate_for_agent("cee-lo")
        config.surface_inbound = False
        # Directly upsert to bypass the normal flow
        registry._upsert(config)

        visible_in, mode_in = registry.check("cee-lo", "inbound")
        visible_out, mode_out = registry.check("cee-lo", "outbound")
        assert visible_in is False
        assert mode_in == "on"
        assert visible_out is True
        assert mode_out == "on"

    def test_check_outbound_only(self, registry):
        """When surface_outbound is False, outbound check returns False."""
        config = registry.generate_for_agent("cee-lo")
        config.surface_outbound = False
        registry._upsert(config)

        visible_in, mode_in = registry.check("cee-lo", "inbound")
        visible_out, mode_out = registry.check("cee-lo", "outbound")
        assert visible_in is True
        assert mode_in == "on"
        assert visible_out is False
        assert mode_out == "on"


# ── set_mode() ─────────────────────────────────────────────────────────

class TestSetMode:
    def test_set_mode_on_to_off(self, registry):
        registry.generate_for_agent("cee-lo")
        config = registry.set_mode("cee-lo", "off")
        assert config.display_mode == "off"
        # Verify persistence
        visible, mode = registry.check("cee-lo", "inbound")
        assert mode == "off"

    def test_set_mode_to_off(self, registry):
        registry.generate_for_agent("cee-lo")
        config = registry.set_mode("cee-lo", "off")
        assert config.display_mode == "off"

    def test_set_mode_updates_timestamp(self, registry):
        c1 = registry.generate_for_agent("cee-lo")
        import time
        time.sleep(0.01)
        c2 = registry.set_mode("cee-lo", "off")
        assert c2.generated_at > c1.generated_at

    def test_set_mode_invalid(self, registry):
        registry.generate_for_agent("cee-lo")
        with pytest.raises(ValueError, match="mode"):
            registry.set_mode("cee-lo", "invisible")

    def test_set_mode_auto_generates(self, registry):
        """set_mode on unknown agent should auto-generate then update."""
        config = registry.set_mode("new-agent", "off")
        assert config.agent_id == "new-agent"
        assert config.display_mode == "off"


# ── list_all() ─────────────────────────────────────────────────────────

class TestListAll:
    def test_list_all_empty(self, registry):
        assert registry.list_all() == []

    def test_list_all_after_generation(self, registry):
        registry.generate_for_agent("a")
        registry.generate_for_agent("b")
        all_configs = registry.list_all()
        assert len(all_configs) == 2
        for c in all_configs:
            assert isinstance(c, VisibilityConfig)

    def test_list_all_reflects_mode_changes(self, registry):
        registry.generate_for_agent("cee-lo")
        registry.set_mode("cee-lo", "off")
        all_configs = registry.list_all()
        cee_lo = next(c for c in all_configs if c.agent_id == "cee-lo")
        assert cee_lo.display_mode == "off"


# ── schema validation ──────────────────────────────────────────────────

class TestSchemaValidation:
    def test_valid_config(self):
        errors = validate_config({
            "agent_id": "cee-lo",
            "display_mode": "on",
        })
        assert errors == []

    def test_missing_agent_id(self):
        errors = validate_config({"display_mode": "on"})
        assert any("agent_id" in e for e in errors)

    def test_empty_agent_id(self):
        errors = validate_config({"agent_id": "", "display_mode": "on"})
        assert any("agent_id" in e for e in errors)

    def test_missing_display_mode(self):
        errors = validate_config({"agent_id": "cee-lo"})
        assert any("display_mode" in e for e in errors)

    def test_invalid_display_mode(self):
        errors = validate_config({
            "agent_id": "cee-lo",
            "display_mode": "invisible",
        })
        assert any("display_mode" in e for e in errors)

    def test_valid_modes(self):
        for mode in ("on", "off"):
            errors = validate_config({
                "agent_id": "test",
                "display_mode": mode,
            })
            assert errors == [], f"mode {mode!r} should be valid"

    def test_bad_surface_flags(self):
        errors = validate_config({
            "agent_id": "test",
            "display_mode": "on",
            "surface_inbound": "yes",
        })
        assert any("surface_inbound" in e for e in errors)

    def test_duplicate_agent_ids(self):
        errors = validate_registry([
            {"agent_id": "dup", "display_mode": "on"},
            {"agent_id": "dup", "display_mode": "off"},
        ])
        assert any("duplicate" in e for e in errors)

    def test_not_a_list(self):
        errors = validate_registry({"not": "a list"})
        assert any("array" in e for e in errors)

    def test_save_rejects_invalid(self, registry):
        with pytest.raises(ValueError, match="schema validation failed"):
            registry._save([{"agent_id": "", "display_mode": "bogus"}])


# ── persistence ────────────────────────────────────────────────────────

class TestPersistence:
    def test_data_survives_reload(self, tmp_registry_path):
        r1 = FileVisibilityRegistry(tmp_registry_path)
        r1.generate_for_agent("cee-lo")
        r1.set_mode("cee-lo", "off")

        # Reload from disk
        r2 = FileVisibilityRegistry(tmp_registry_path)
        config = r2.generate_for_agent("cee-lo")
        assert config.display_mode == "off"

    def test_file_is_valid_json(self, tmp_registry_path):
        r1 = FileVisibilityRegistry(tmp_registry_path)
        r1.generate_for_agent("cee-lo")
        r1.generate_for_agent("cactus-jack")

        raw = Path(tmp_registry_path).read_text()
        data = json.loads(raw)
        assert isinstance(data, list)
        assert len(data) == 2
        for entry in data:
            assert isinstance(entry.get("agent_id"), str)
            assert entry.get("display_mode") in ("on", "off", "off")

    def test_atomic_write_no_partial(self, tmp_registry_path):
        r1 = FileVisibilityRegistry(tmp_registry_path)
        r1.generate_for_agent("cee-lo")

        before = Path(tmp_registry_path).read_text()
        data_before = json.loads(before)

        with pytest.raises(ValueError):
            r1._save([{"agent_id": "", "display_mode": "bogus"}])

        after = Path(tmp_registry_path).read_text()
        data_after = json.loads(after)
        assert data_after == data_before

    def test_no_temp_file_left_behind(self, tmp_registry_path):
        r1 = FileVisibilityRegistry(tmp_registry_path)
        r1.generate_for_agent("cee-lo")

        tmp_path = Path(str(tmp_registry_path) + ".tmp")
        assert not tmp_path.exists()
