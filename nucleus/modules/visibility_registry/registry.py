"""Visibility Registry — file-backed, schema-validated visibility store.

Guarantees
----------
* Schema validation   — every write is validated; malformed entries are rejected.
* Atomic replace      — writes land in a temp file, then ``os.rename()``.
* Default generation  — any agent not yet configured gets "on" mode with
  inbound+outbound on and system off.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .interface import VisibilityConfig, VisibilityRegistry
from .schema import validate_registry

# ── defaults ───────────────────────────────────────────────────────────

DEFAULT_MODE = "on"
DEFAULT_SURFACE_INBOUND = True
DEFAULT_SURFACE_OUTBOUND = True
DEFAULT_SURFACE_SYSTEM = False


class FileVisibilityRegistry(VisibilityRegistry):
    """File-backed visibility registry."""

    def __init__(
        self, registry_path: str = "nucleus/data/visibility.json"
    ) -> None:
        self._path = Path(registry_path).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ── public API ─────────────────────────────────────────────────────

    def check(self, agent_id: str, direction: str) -> tuple[bool, str]:
        """Return (visible, mode) for *agent_id* in *direction*.

        *direction* must be "inbound" or "outbound".

        If the agent has no config, a default is generated first.
        If display_mode is "off", returns (False, "off") regardless of
        surface flags.
        """
        if direction not in ("inbound", "outbound"):
            raise ValueError(
                f"direction must be 'inbound' or 'outbound', got {direction!r}"
            )

        config = self._get_or_generate(agent_id)

        if config.display_mode == "off":
            return (False, "off")

        if direction == "inbound":
            return (config.surface_inbound, config.display_mode)
        else:
            return (config.surface_outbound, config.display_mode)

    def set_mode(self, agent_id: str, mode: str) -> VisibilityConfig:
        """Set the display mode for *agent_id*.  Returns the updated config.

        *mode* must be "on" or "off".
        """
        if mode not in ("on", "off"):
            raise ValueError(
                f"mode must be 'on' or 'off', got {mode!r}"
            )

        config = self._get_or_generate(agent_id)
        config.display_mode = mode
        config.generated_at = int(time.time() * 1000)
        self._upsert(config)
        return config

    def generate_for_agent(self, agent_id: str) -> VisibilityConfig:
        """Generate (or return existing) default config for *agent_id*."""
        return self._get_or_generate(agent_id)

    def list_all(self) -> list[VisibilityConfig]:
        """Return every visibility config currently stored."""
        return [self._dict_to_config(e) for e in self._load()]

    # ── internal helpers ───────────────────────────────────────────────

    def _load(self) -> list[dict[str, Any]]:
        """Read the visibility registry file."""
        if not self._path.exists():
            return []
        try:
            raw = self._path.read_text(encoding="utf-8")
            return json.loads(raw) if raw.strip() else []
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save(self, data: list[dict[str, Any]]) -> None:
        """Validate, then atomically write *data* to the registry file."""
        errors = validate_registry(data)
        if errors:
            raise ValueError(f"schema validation failed: {'; '.join(errors)}")

        payload = json.dumps(data, indent=2)
        tmp_path = str(self._path) + ".tmp"

        with open(tmp_path, "w", encoding="utf-8") as tf:
            tf.write(payload)
            tf.flush()
            os.fsync(tf.fileno())

        os.rename(tmp_path, str(self._path))

    def _upsert(self, config: VisibilityConfig) -> None:
        """Insert or update a single config record."""
        data = self._load()
        data = [e for e in data if e.get("agent_id") != config.agent_id]
        data.append(self._config_to_dict(config))
        self._save(data)

    def _get_or_generate(self, agent_id: str) -> VisibilityConfig:
        """Return existing config for *agent_id*, or generate a default."""
        for entry in self._load():
            if entry.get("agent_id") == agent_id:
                return self._dict_to_config(entry)

        # Generate default
        config = VisibilityConfig(
            agent_id=agent_id,
            display_mode=DEFAULT_MODE,
            surface_inbound=DEFAULT_SURFACE_INBOUND,
            surface_outbound=DEFAULT_SURFACE_OUTBOUND,
            surface_system=DEFAULT_SURFACE_SYSTEM,
            generated_at=int(time.time() * 1000),
        )
        self._upsert(config)
        return config

    # ── conversion helpers ─────────────────────────────────────────────

    @staticmethod
    def _dict_to_config(d: dict[str, Any]) -> VisibilityConfig:
        return VisibilityConfig(
            agent_id=d.get("agent_id", ""),
            display_mode=d.get("display_mode", DEFAULT_MODE),
            surface_inbound=d.get("surface_inbound", DEFAULT_SURFACE_INBOUND),
            surface_outbound=d.get("surface_outbound", DEFAULT_SURFACE_OUTBOUND),
            surface_system=d.get("surface_system", DEFAULT_SURFACE_SYSTEM),
            generated_at=d.get("generated_at", 0),
        )

    @staticmethod
    def _config_to_dict(c: VisibilityConfig) -> dict[str, Any]:
        return {
            "agent_id": c.agent_id,
            "display_mode": c.display_mode,
            "surface_inbound": c.surface_inbound,
            "surface_outbound": c.surface_outbound,
            "surface_system": c.surface_system,
            "generated_at": c.generated_at,
        }
