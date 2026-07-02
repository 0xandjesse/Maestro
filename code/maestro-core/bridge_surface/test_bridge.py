"""Tests for the Bridge Surface module.

Covers:
* surface() returns SurfaceResult with correct platform
* get_display_mode() returns mode from visibility registry
* set_display_mode() updates visibility registry
* Platform routing works for all three platforms
* Visibility check prevents surfacing when mode is "off"
* Schema validation for SurfaceMessage
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from nucleus.modules.bridge_surface import (
    BridgeSurfaceImpl,
    SurfaceMessage,
    SurfaceResult,
    validate_surface_message,
)


# ── fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def tmp_registry_path():
    """Create a temp file path for an isolated visibility registry."""
    fd, path = tempfile.mkstemp(suffix=".json", prefix="test_bridge_")
    os.close(fd)
    yield path
    for suffix in ("", ".tmp"):
        p = Path(path + suffix) if suffix else Path(path)
        if p.exists():
            p.unlink(missing_ok=True)


@pytest.fixture
def bridge(tmp_registry_path):
    """Return a BridgeSurfaceImpl pointed at a temp registry."""
    return BridgeSurfaceImpl(registry_path=tmp_registry_path)


@pytest.fixture
def valid_message():
    """Return a valid SurfaceMessage for testing."""
    return SurfaceMessage(
        agent_id="cee-lo",
        from_agent="proteus",
        content="Build Module 5",
        summary="Proteus assigned Module 5 to Cee-Lo",
        msg_type="direct",
        platform="telegram",
    )


# ── surface() — basic routing ──────────────────────────────────────────

class TestSurface:
    def test_surface_telegram(self, bridge, valid_message):
        result = bridge.surface(valid_message)
        assert result.ok is True
        assert result.displayed is True
        assert result.platform == "telegram"
        assert result.message_id is not None
        assert result.message_id.startswith("tg-")

    def test_surface_discord(self, bridge):
        msg = SurfaceMessage(
            agent_id="cactus-jack",
            from_agent="proteus",
            content="Review PR",
            summary="Proteus asked Cactus Jack to review a PR",
            msg_type="direct",
            platform="discord",
        )
        result = bridge.surface(msg)
        assert result.ok is True
        assert result.displayed is True
        assert result.platform == "discord"
        assert result.message_id.startswith("dc-")

    def test_surface_p2n(self, bridge):
        msg = SurfaceMessage(
            agent_id="stormtrooper",
            from_agent="proteus",
            content="Recompose modules",
            summary="Proteus asked Stormtrooper to recompose",
            msg_type="broadcast",
            platform="p2n",
        )
        result = bridge.surface(msg)
        assert result.ok is True
        assert result.displayed is True
        assert result.platform == "p2n"
        assert result.message_id.startswith("p2n-")

    def test_surface_unknown_platform(self, bridge):
        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="proteus",
            content="test",
            summary="test",
            msg_type="direct",
            platform="slack",
        )
        result = bridge.surface(msg)
        assert result.ok is False
        assert result.displayed is False
        # Validation catches invalid platform before adapter lookup
        assert "platform" in result.detail

    def test_surface_returns_surface_result_type(self, bridge, valid_message):
        result = bridge.surface(valid_message)
        assert isinstance(result, SurfaceResult)


# ── surface() — validation ─────────────────────────────────────────────

class TestSurfaceValidation:
    def test_surface_rejects_empty_agent_id(self, bridge):
        msg = SurfaceMessage(
            agent_id="",
            from_agent="proteus",
            content="test",
            summary="test",
            msg_type="direct",
            platform="telegram",
        )
        result = bridge.surface(msg)
        assert result.ok is False
        assert "validation failed" in result.detail
        assert "agent_id" in result.detail

    def test_surface_rejects_empty_content(self, bridge):
        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="proteus",
            content="",
            summary="test",
            msg_type="direct",
            platform="telegram",
        )
        result = bridge.surface(msg)
        assert result.ok is False
        assert "content" in result.detail

    def test_surface_rejects_invalid_msg_type(self, bridge):
        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="proteus",
            content="test",
            summary="test",
            msg_type="bogus",
            platform="telegram",
        )
        result = bridge.surface(msg)
        assert result.ok is False
        assert "msg_type" in result.detail

    def test_surface_rejects_invalid_platform(self, bridge):
        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="proteus",
            content="test",
            summary="test",
            msg_type="direct",
            platform="bogus",
        )
        result = bridge.surface(msg)
        assert result.ok is False
        assert "platform" in result.detail


# ── display modes ──────────────────────────────────────────────────────

class TestDisplayModes:
    def test_get_display_mode_default(self, bridge):
        mode = bridge.get_display_mode("cee-lo")
        assert mode == "long"

    def test_get_display_mode_after_set(self, bridge):
        bridge.set_display_mode("cee-lo", "short")
        mode = bridge.get_display_mode("cee-lo")
        assert mode == "short"

    def test_set_display_mode_returns_true(self, bridge):
        result = bridge.set_display_mode("cee-lo", "short")
        assert result is True

    def test_set_display_mode_invalid_returns_false(self, bridge):
        result = bridge.set_display_mode("cee-lo", "bogus")
        assert result is False

    def test_set_display_mode_off(self, bridge):
        bridge.set_display_mode("cee-lo", "off")
        mode = bridge.get_display_mode("cee-lo")
        assert mode == "off"

    def test_set_display_mode_all_valid(self, bridge):
        for mode in ("long", "short", "off"):
            result = bridge.set_display_mode("cee-lo", mode)
            assert result is True
            assert bridge.get_display_mode("cee-lo") == mode


# ── visibility gating ──────────────────────────────────────────────────

class TestVisibilityGating:
    def test_off_mode_blocks_surface(self, bridge):
        bridge.set_display_mode("cee-lo", "off")
        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="proteus",
            content="test",
            summary="test",
            msg_type="direct",
            platform="telegram",
        )
        result = bridge.surface(msg)
        assert result.ok is False
        assert result.displayed is False
        assert "off" in result.detail

    def test_off_mode_blocks_broadcast(self, bridge):
        bridge.set_display_mode("cee-lo", "off")
        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="proteus",
            content="broadcast test",
            summary="broadcast",
            msg_type="broadcast",
            platform="telegram",
        )
        result = bridge.surface(msg)
        assert result.ok is False
        assert result.displayed is False

    def test_off_mode_blocks_system(self, bridge):
        bridge.set_display_mode("cee-lo", "off")
        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="system",
            content="system test",
            summary="system",
            msg_type="system",
            platform="telegram",
        )
        result = bridge.surface(msg)
        assert result.ok is False
        assert result.displayed is False

    def test_system_messages_respect_surface_system(self, bridge):
        # Default: surface_system is False, so system messages should be blocked
        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="system",
            content="system alert",
            summary="system alert",
            msg_type="system",
            platform="telegram",
        )
        result = bridge.surface(msg)
        assert result.ok is False
        assert "surface_system" in result.detail

    def test_surface_inbound_disabled_blocks_direct(self, bridge):
        # Manually disable surface_inbound via the registry
        config = bridge._registry.generate_for_agent("cee-lo")
        config.surface_inbound = False
        bridge._registry._upsert(config)

        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="proteus",
            content="test",
            summary="test",
            msg_type="direct",
            platform="telegram",
        )
        result = bridge.surface(msg)
        assert result.ok is False
        assert "surface_inbound" in result.detail

    def test_surface_inbound_disabled_blocks_broadcast(self, bridge):
        config = bridge._registry.generate_for_agent("cee-lo")
        config.surface_inbound = False
        bridge._registry._upsert(config)

        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="proteus",
            content="broadcast",
            summary="broadcast",
            msg_type="broadcast",
            platform="telegram",
        )
        result = bridge.surface(msg)
        assert result.ok is False
        assert "surface_inbound" in result.detail

    def test_long_mode_allows_surface(self, bridge):
        bridge.set_display_mode("cee-lo", "long")
        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="proteus",
            content="test",
            summary="test",
            msg_type="direct",
            platform="telegram",
        )
        result = bridge.surface(msg)
        assert result.ok is True
        assert result.displayed is True

    def test_short_mode_allows_surface(self, bridge):
        bridge.set_display_mode("cee-lo", "short")
        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="proteus",
            content="test",
            summary="test",
            msg_type="direct",
            platform="telegram",
        )
        result = bridge.surface(msg)
        assert result.ok is True
        assert result.displayed is True


# ── platform routing ───────────────────────────────────────────────────

class TestPlatformRouting:
    def test_telegram_routing(self, bridge):
        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="proteus",
            content="test",
            summary="test",
            msg_type="direct",
            platform="telegram",
        )
        result = bridge.surface(msg)
        assert result.platform == "telegram"
        assert result.message_id.startswith("tg-")

    def test_discord_routing(self, bridge):
        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="proteus",
            content="test",
            summary="test",
            msg_type="direct",
            platform="discord",
        )
        result = bridge.surface(msg)
        assert result.platform == "discord"
        assert result.message_id.startswith("dc-")

    def test_p2n_routing(self, bridge):
        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="proteus",
            content="test",
            summary="test",
            msg_type="direct",
            platform="p2n",
        )
        result = bridge.surface(msg)
        assert result.platform == "p2n"
        assert result.message_id.startswith("p2n-")

    def test_broadcast_routing(self, bridge):
        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="proteus",
            content="broadcast",
            summary="broadcast",
            msg_type="broadcast",
            platform="telegram",
        )
        result = bridge.surface(msg)
        assert result.ok is True
        assert result.platform == "telegram"


# ── schema validation ─────────────────────────────────────────────────

class TestSchemaValidation:
    def test_valid_message(self):
        errors = validate_surface_message({
            "agent_id": "cee-lo",
            "from_agent": "proteus",
            "content": "test",
            "summary": "test",
            "msg_type": "direct",
            "platform": "telegram",
        })
        assert errors == []

    def test_missing_agent_id(self):
        errors = validate_surface_message({
            "from_agent": "proteus",
            "content": "test",
            "summary": "test",
            "msg_type": "direct",
            "platform": "telegram",
        })
        assert any("agent_id" in e for e in errors)

    def test_missing_from_agent(self):
        errors = validate_surface_message({
            "agent_id": "cee-lo",
            "content": "test",
            "summary": "test",
            "msg_type": "direct",
            "platform": "telegram",
        })
        assert any("from_agent" in e for e in errors)

    def test_missing_content(self):
        errors = validate_surface_message({
            "agent_id": "cee-lo",
            "from_agent": "proteus",
            "summary": "test",
            "msg_type": "direct",
            "platform": "telegram",
        })
        assert any("content" in e for e in errors)

    def test_missing_summary(self):
        errors = validate_surface_message({
            "agent_id": "cee-lo",
            "from_agent": "proteus",
            "content": "test",
            "msg_type": "direct",
            "platform": "telegram",
        })
        assert any("summary" in e for e in errors)

    def test_invalid_msg_type(self):
        errors = validate_surface_message({
            "agent_id": "cee-lo",
            "from_agent": "proteus",
            "content": "test",
            "summary": "test",
            "msg_type": "bogus",
            "platform": "telegram",
        })
        assert any("msg_type" in e for e in errors)

    def test_invalid_platform(self):
        errors = validate_surface_message({
            "agent_id": "cee-lo",
            "from_agent": "proteus",
            "content": "test",
            "summary": "test",
            "msg_type": "direct",
            "platform": "bogus",
        })
        assert any("platform" in e for e in errors)

    def test_not_a_dict(self):
        errors = validate_surface_message("not a dict")
        assert any("not a dict" in e for e in errors)

    def test_all_valid_msg_types(self):
        for mt in ("direct", "broadcast", "system"):
            errors = validate_surface_message({
                "agent_id": "cee-lo",
                "from_agent": "proteus",
                "content": "test",
                "summary": "test",
                "msg_type": mt,
                "platform": "telegram",
            })
            assert errors == [], f"msg_type {mt!r} should be valid"

    def test_all_valid_platforms(self):
        for pf in ("telegram", "discord", "p2n"):
            errors = validate_surface_message({
                "agent_id": "cee-lo",
                "from_agent": "proteus",
                "content": "test",
                "summary": "test",
                "msg_type": "direct",
                "platform": pf,
            })
            assert errors == [], f"platform {pf!r} should be valid"


# ── integration ────────────────────────────────────────────────────────

class TestIntegration:
    def test_full_cycle(self, bridge):
        """End-to-end: set mode, surface, verify."""
        # Set mode to short
        assert bridge.set_display_mode("cee-lo", "short") is True
        assert bridge.get_display_mode("cee-lo") == "short"

        # Surface a message
        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="proteus",
            content="Build Module 5",
            summary="Proteus assigned Module 5 to Cee-Lo",
            msg_type="direct",
            platform="telegram",
        )
        result = bridge.surface(msg)
        assert result.ok is True
        assert result.displayed is True
        assert result.platform == "telegram"

        # Turn off and verify blocking
        bridge.set_display_mode("cee-lo", "off")
        result2 = bridge.surface(msg)
        assert result2.ok is False
        assert result2.displayed is False

    def test_multiple_agents_independent_modes(self, bridge):
        """Each agent has independent display modes."""
        bridge.set_display_mode("cee-lo", "short")
        bridge.set_display_mode("cactus-jack", "off")

        assert bridge.get_display_mode("cee-lo") == "short"
        assert bridge.get_display_mode("cactus-jack") == "off"

        # cee-lo can still receive
        msg = SurfaceMessage(
            agent_id="cee-lo",
            from_agent="proteus",
            content="test",
            summary="test",
            msg_type="direct",
            platform="telegram",
        )
        result = bridge.surface(msg)
        assert result.ok is True

        # cactus-jack is blocked
        msg2 = SurfaceMessage(
            agent_id="cactus-jack",
            from_agent="proteus",
            content="test",
            summary="test",
            msg_type="direct",
            platform="telegram",
        )
        result2 = bridge.surface(msg2)
        assert result2.ok is False
