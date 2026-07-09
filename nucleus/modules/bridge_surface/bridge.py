"""Bridge Surface — platform-routing surface with visibility gating.

Routes SurfaceMessages to platform adapters after checking the
Visibility Registry for display permissions.  Platform adapters are
stub implementations — they return success without making real
platform calls.
"""

from __future__ import annotations

import uuid
from typing import Any

from .interface import BridgeSurface, SurfaceMessage, SurfaceResult
from .schema import validate_surface_message

# Import Visibility Registry
from nucleus.modules.visibility_registry import FileVisibilityRegistry, VisibilityConfig


# ── platform adapter stubs ─────────────────────────────────────────────

def _telegram_adapter(msg: SurfaceMessage) -> SurfaceResult:
    """Stub: pretend to surface a message to Telegram."""
    return SurfaceResult(
        ok=True,
        displayed=True,
        platform="telegram",
        message_id=f"tg-{uuid.uuid4().hex[:12]}",
        detail="routed to telegram stub",
    )


def _discord_adapter(msg: SurfaceMessage) -> SurfaceResult:
    """Stub: pretend to surface a message to Discord."""
    return SurfaceResult(
        ok=True,
        displayed=True,
        platform="discord",
        message_id=f"dc-{uuid.uuid4().hex[:12]}",
        detail="routed to discord stub",
    )


def _p2n_adapter(msg: SurfaceMessage) -> SurfaceResult:
    """Stub: pretend to surface a message via P2N."""
    return SurfaceResult(
        ok=True,
        displayed=True,
        platform="p2n",
        message_id=f"p2n-{uuid.uuid4().hex[:12]}",
        detail="routed to p2n stub",
    )


# ── platform router ────────────────────────────────────────────────────

_PLATFORM_ADAPTERS: dict[str, Any] = {
    "telegram": _telegram_adapter,
    "discord": _discord_adapter,
    "p2n": _p2n_adapter,
}


# ── BridgeSurface implementation ───────────────────────────────────────

class BridgeSurfaceImpl(BridgeSurface):
    """Concrete bridge surface with visibility gating and platform stubs."""

    def __init__(
        self,
        registry_path: str = "nucleus/data/visibility.json",
    ) -> None:
        self._registry = FileVisibilityRegistry(registry_path=registry_path)

    # ── public API ─────────────────────────────────────────────────────

    def surface(self, message: SurfaceMessage) -> SurfaceResult:
        """Route *message* to the appropriate platform for display.

        Validates the message, checks visibility, then dispatches to
        the correct platform adapter.  Returns a SurfaceResult.
        """
        # Validate
        msg_dict = {
            "agent_id": message.agent_id,
            "from_agent": message.from_agent,
            "content": message.content,
            "summary": message.summary,
            "msg_type": message.msg_type,
            "platform": message.platform,
        }
        errors = validate_surface_message(msg_dict)
        if errors:
            return SurfaceResult(
                ok=False,
                displayed=False,
                platform=message.platform,
                detail=f"validation failed: {'; '.join(errors)}",
            )

        # Visibility check
        visible, reason = self._check_visibility(message)
        if not visible:
            return SurfaceResult(
                ok=False,
                displayed=False,
                platform=message.platform,
                detail=reason,
            )

        # Route to platform adapter
        adapter = _PLATFORM_ADAPTERS.get(message.platform)
        if adapter is None:
            return SurfaceResult(
                ok=False,
                displayed=False,
                platform=message.platform,
                detail=f"unknown platform: {message.platform!r}",
            )

        return adapter(message)

    def get_display_mode(self, agent_id: str) -> str:
        """Query the visibility registry for *agent_id*'s display mode."""
        config = self._registry.generate_for_agent(agent_id)
        return config.display_mode

    def set_display_mode(self, agent_id: str, mode: str) -> bool:
        """Update *agent_id*'s display mode in the visibility registry.

        Returns True if the update succeeded.
        """
        try:
            self._registry.set_mode(agent_id, mode)
            return True
        except (ValueError, OSError):
            return False

    # ── internal helpers ───────────────────────────────────────────────

    def _check_visibility(
        self, message: SurfaceMessage
    ) -> tuple[bool, str]:
        """Check whether *message* should be surfaced for its target agent.

        Returns (visible, reason).
        """
        config = self._registry.generate_for_agent(message.agent_id)

        # Mode "off" blocks everything
        if config.display_mode == "off":
            return (False, f"display_mode is 'off' for {message.agent_id}")

        # System messages check surface_system
        if message.msg_type == "system":
            if not config.surface_system:
                return (
                    False,
                    f"surface_system is disabled for {message.agent_id}",
                )
            return (True, "ok")

        # Direct and broadcast messages check surface_inbound
        if not config.surface_inbound:
            return (
                False,
                f"surface_inbound is disabled for {message.agent_id}",
            )

        return (True, "ok")
