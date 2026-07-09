# nucleus/modules/config_generator/generator.py
"""Config Generator — file-backed implementation.

Reads the registry from ``~/.maestro/registry.json`` and queries
Port Authority for transport port assignments.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .interface import AgentConfig, ConfigGenerator, ConfigTemplate
from .schema import validate_config

# ── Port Authority import ───────────────────────────────────────────────
from ..port_authority import FilePortAuthority

# ── constants ──────────────────────────────────────────────────────────

DEFAULT_REGISTRY_PATH = os.path.expanduser("~/.maestro/registry.json")
DEFAULT_CONFIGS_DIR = str(
    Path(__file__).resolve().parent.parent.parent / "data" / "configs"
)
DEFAULT_HERMES_API_URL = "http://127.0.0.1:8641"  # hermes gateway API


class FileConfigGenerator(ConfigGenerator):
    """File-backed config generator.

    Parameters
    ----------
    port_map_path : str
        Path to the Port Authority port map file.
    registry_path : str
        Path to the agent registry JSON file.
    configs_dir : str
        Directory where per-agent config files are written.
    """

    def __init__(
        self,
        port_map_path: str = (
            "/home/andjesse/Projects/Maestro/nucleus/data/port_map.json"
        ),
        registry_path: str = DEFAULT_REGISTRY_PATH,
        configs_dir: str = DEFAULT_CONFIGS_DIR,
    ) -> None:
        self._port_authority = FilePortAuthority(port_map_path)
        self._registry_path = Path(registry_path)
        self._configs_dir = Path(configs_dir)
        self._configs_dir.mkdir(parents=True, exist_ok=True)

    # ── public API ─────────────────────────────────────────────────────

    def generate(
        self, agent_id: str, overrides: dict | None = None
    ) -> AgentConfig:
        """Create an AgentConfig from template + overrides.

        * Port is resolved from Port Authority.
        * hermesApiUrl is built from the agent's own gateway port.
        * knownPeers is built from the registry.
        * Template defaults are applied, then overrides on top.
        """
        overrides = overrides or {}
        template = ConfigTemplate()

        # ── resolve ports from Port Authority ────────────────────────
        try:
            assignment = self._port_authority.resolve(agent_id)
            port = assignment.transport_port
            gateway_port = assignment.gateway_port
        except KeyError:
            raise KeyError(
                f"Agent '{agent_id}' not found in port map. "
                f"Register the agent with Port Authority first."
            )

        # ── build hermesApiUrl from agent's own gateway port ────────
        hermes_api_url = f"http://127.0.0.1:{gateway_port}"

        # ── build knownPeers from registry ─────────────────────────
        known_peers = self._build_known_peers(agent_id)

        # ── apply template defaults, then overrides ────────────────
        config = AgentConfig(
            agentId=agent_id,
            port=port,
            hermesApiUrl=overrides.get(
                "hermesApiUrl", hermes_api_url
            ),
            hermesApiKey=overrides.get(
                "hermesApiKey", template.hermesApiKey
            ),
            conversation=overrides.get("conversation", ""),
            registryPath=overrides.get(
                "registryPath", template.registryPath
            ),
            version=overrides.get("version", template.version),
            knownPeers=known_peers,
            surfaceToGateway=overrides.get(
                "surfaceToGateway", template.surfaceToGateway
            ),
            gatewayBridgeUrl=overrides.get(
                "gatewayBridgeUrl", template.gatewayBridgeUrl
            ),
            dm_policy=overrides.get("dm_policy"),
            registry_signer_public_key=overrides.get(
                "registry_signer_public_key"
            ),
        )

        return config

    def validate(self, config: AgentConfig) -> list[str]:
        """Validate *config* and return a list of issues (empty = valid)."""
        return validate_config(config)

    def write(self, agent_id: str, config: AgentConfig) -> str:
        """Persist *config* to disk with an atomic write.

        Returns the absolute path to the written file.
        """
        out_path = self._configs_dir / f"{agent_id}.json"
        payload = json.dumps(self._config_to_dict(config), indent=2)

        # Atomic write: temp file → fsync → rename
        tmp_path = str(out_path) + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_path, str(out_path))

        return str(out_path.resolve())

    def regenerate_all(self) -> dict[str, AgentConfig]:
        """Regenerate configs for all known agents, preserving existing overrides.

        Returns a dict of agent_id → AgentConfig.
        """
        agents = self._load_registry()
        results: dict[str, AgentConfig] = {}

        for entry in agents:
            agent_id = entry.get("agentId", "")
            if not agent_id:
                continue
            try:
                # Load existing config to preserve agent-specific overrides
                existing = self._load_existing_config(agent_id)
                overrides = self._extract_overrides(existing)
                config = self.generate(agent_id, overrides=overrides)
                results[agent_id] = config
            except KeyError:
                # Agent not in port map — skip
                continue

        return results

    def _load_existing_config(self, agent_id: str) -> dict[str, Any]:
        """Load an existing config file if it exists, return empty dict otherwise."""
        config_path = self._configs_dir / f"{agent_id}.json"
        if not config_path.exists():
            return {}
        try:
            raw = config_path.read_text(encoding="utf-8")
            return json.loads(raw) if raw.strip() else {}
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    @staticmethod
    def _extract_overrides(existing: dict[str, Any]) -> dict[str, Any]:
        """Extract agent-specific overrides from an existing config.

        These are fields that Port Authority does NOT own — they're
        agent-specific and should be preserved across regeneration.
        """
        override_keys = [
            "conversation",
            "dm_policy",
            "registry_signer_public_key",
            "hermesApiKey",
            "version",
            "registryPath",
        ]
        return {k: v for k, v in existing.items() if k in override_keys and v}

    # ── internal helpers ───────────────────────────────────────────────

    def _load_registry(self) -> list[dict[str, Any]]:
        """Load the agent registry from disk."""
        if not self._registry_path.exists():
            return []
        try:
            raw = self._registry_path.read_text(encoding="utf-8")
            return json.loads(raw) if raw.strip() else []
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _build_known_peers(self, agent_id: str) -> dict[str, str]:
        """Build a knownPeers dict from the registry, excluding *agent_id*."""
        agents = self._load_registry()
        peers: dict[str, str] = {}
        for entry in agents:
            aid = entry.get("agentId", "")
            if aid and aid != agent_id:
                endpoint = entry.get("webhookEndpoint", "")
                if endpoint:
                    peers[aid] = endpoint
        return peers

    @staticmethod
    def _config_to_dict(config: AgentConfig) -> dict[str, Any]:
        """Serialize an AgentConfig to a JSON-safe dict."""
        return {
            "agentId": config.agentId,
            "port": config.port,
            "hermesApiUrl": config.hermesApiUrl,
            "hermesApiKey": config.hermesApiKey,
            "conversation": config.conversation,
            "registryPath": config.registryPath,
            "version": config.version,
            "knownPeers": config.knownPeers,
            "surfaceToGateway": config.surfaceToGateway,
            "gatewayBridgeUrl": config.gatewayBridgeUrl,
            "dm_policy": config.dm_policy,
            "registry_signer_public_key": config.registry_signer_public_key,
        }
