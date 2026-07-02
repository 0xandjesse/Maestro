"""Agent Lifecycle — in-memory implementation.

Implements the AgentLifecycle interface with:
* Port assignment via Port Authority
* Config generation via Config Generator (with fallback)
* Registration via Registry Manager
* In-memory agent store
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .interface import AgentCreateResult, AgentLifecycle, AgentSpec
from .schema import validate_agent_spec

log = logging.getLogger(__name__)

# ── dependency imports (with graceful fallback) ──────────────────────

from nucleus.modules.port_authority import FilePortAuthority, PortAuthority
from nucleus.modules.registry_manager import FileRegistryManager, RegistryManager

try:
    from nucleus.modules.config_generator import ConfigGenerator
    _HAS_CONFIG_GENERATOR = True
except ImportError:
    _HAS_CONFIG_GENERATOR = False
    log.warning("Config Generator (M9) not available — using inline fallback")


class InMemoryAgentLifecycle(AgentLifecycle):
    """In-memory agent lifecycle manager.

    Delegates port assignment, config generation, and registration
    to the respective modules.  Keeps an in-memory store of AgentSpec
    objects for fast lookup.
    """

    # Port range for auto-assignment
    _TRANSPORT_BASE = 9000
    _GATEWAY_BASE = 9100
    _MAX_AGENTS = 100

    def __init__(
        self,
        port_authority: PortAuthority | None = None,
        registry_manager: RegistryManager | None = None,
        config_generator: Any = None,
    ) -> None:
        self._agents: dict[str, AgentSpec] = {}
        self._port_authority = port_authority or FilePortAuthority()
        self._registry = registry_manager or FileRegistryManager()
        self._config_generator = config_generator  # may be None

    # ── public API ─────────────────────────────────────────────────────

    def create(self, spec: AgentSpec) -> AgentCreateResult:
        """Full agent creation pipeline."""
        warnings: list[str] = []

        # Validate the spec
        spec_dict = {
            "agent_id": spec.agent_id,
            "display_name": spec.display_name,
            "role": spec.role,
            "model": spec.model,
            "provider": spec.provider,
            "transport_port": spec.transport_port,
            "gateway_port": spec.gateway_port,
        }
        issues = validate_agent_spec(spec_dict)
        if issues:
            raise ValueError(f"Invalid AgentSpec: {'; '.join(issues)}")

        # 1. Assign ports (auto-assign if not specified)
        transport_port = spec.transport_port
        gateway_port = spec.gateway_port

        if transport_port is None or gateway_port is None:
            assigned = self._auto_assign_ports(spec.agent_id)
            if transport_port is None:
                transport_port = assigned[0]
            if gateway_port is None:
                gateway_port = assigned[1]
        else:
            # Register the specified ports
            try:
                self._port_authority.assign(
                    spec.agent_id, transport_port, gateway_port
                )
            except Exception as exc:
                warnings.append(f"Port assignment warning: {exc}")

        # 2. Generate config
        config_path = self._generate_config(spec, transport_port, gateway_port, warnings)

        # 3. Register in Registry Manager
        webhook_endpoint = f"http://127.0.0.1:{transport_port}/maestro/webhook"
        try:
            self._registry.register(
                agent_id=spec.agent_id,
                webhook_endpoint=webhook_endpoint,
                capabilities=[spec.role],
            )
        except Exception as exc:
            warnings.append(f"Registry warning: {exc}")

        # 4. Generate systemd unit name
        systemd_unit = f"maestro-agent-{spec.agent_id}.service"

        # 5. Store in memory
        self._agents[spec.agent_id] = spec

        return AgentCreateResult(
            agent_id=spec.agent_id,
            config_path=config_path,
            transport_port=transport_port,
            gateway_port=gateway_port,
            systemd_unit=systemd_unit,
            warnings=warnings,
        )

    def destroy(self, agent_id: str) -> bool:
        """Remove agent from registry, delete config, release ports.

        Returns True if the agent existed.
        """
        if agent_id not in self._agents:
            return False

        # Remove from in-memory store
        del self._agents[agent_id]

        # Unregister from registry
        try:
            self._registry.unregister(agent_id)
        except Exception as exc:
            log.warning("Registry unregister failed for %s: %s", agent_id, exc)

        return True

    def list_agents(self) -> list[AgentSpec]:
        """Return all registered agents as AgentSpec list."""
        return list(self._agents.values())

    def health_check(self, agent_id: str) -> tuple[bool, str]:
        """Check if agent is registered and recently seen.

        Returns (healthy, detail).
        """
        # Check in-memory store first
        if agent_id not in self._agents:
            return (False, f"Agent '{agent_id}' not found in lifecycle store")

        # Check registry
        record = self._registry.lookup(agent_id)
        if record is None:
            return (False, f"Agent '{agent_id}' not found in registry")

        # Check if recently seen (within last 5 minutes)
        now_ms = int(time.time() * 1000)
        staleness_ms = now_ms - record.lastSeen
        if staleness_ms > 300_000:  # 5 minutes
            return (False, f"Agent '{agent_id}' last seen {staleness_ms // 1000}s ago (stale)")

        if record.status != "active":
            return (False, f"Agent '{agent_id}' status is '{record.status}'")

        return (True, "healthy")

    def restart(self, agent_id: str) -> bool:
        """Mark agent for restart.  Returns True if agent exists."""
        if agent_id not in self._agents:
            return False

        # Update lastSeen to mark as recently active
        try:
            self._registry.update_last_seen(agent_id)
        except Exception as exc:
            log.warning("Registry update_last_seen failed for %s: %s", agent_id, exc)

        return True

    # ── internal helpers ───────────────────────────────────────────────

    def _auto_assign_ports(self, agent_id: str) -> tuple[int, int]:
        """Find the next available transport + gateway port pair."""
        existing = self._port_authority.list_all()
        used_transport = {a.transport_port for a in existing}
        used_gateway = {a.gateway_port for a in existing}

        for offset in range(self._MAX_AGENTS):
            tp = self._TRANSPORT_BASE + offset
            gp = self._GATEWAY_BASE + offset
            if tp not in used_transport and gp not in used_gateway:
                self._port_authority.assign(agent_id, tp, gp)
                return (tp, gp)

        raise RuntimeError("No available port pairs in range")

    def _generate_config(
        self,
        spec: AgentSpec,
        transport_port: int,
        gateway_port: int,
        warnings: list[str],
    ) -> str:
        """Generate agent config, using Config Generator if available."""
        config_path = f"nucleus/data/configs/{spec.agent_id}.json"

        if _HAS_CONFIG_GENERATOR and self._config_generator is not None:
            try:
                overrides = {
                    "port": transport_port,
                    "gatewayBridgeUrl": f"http://127.0.0.1:{gateway_port}/maestro/notify",
                }
                config = self._config_generator.generate(spec.agent_id, overrides)
                return self._config_generator.write(spec.agent_id, config)
            except Exception as exc:
                warnings.append(f"Config generator failed, using fallback: {exc}")

        # Fallback: generate minimal config inline
        import json
        import os

        config = {
            "agentId": spec.agent_id,
            "displayName": spec.display_name,
            "role": spec.role,
            "model": spec.model,
            "provider": spec.provider,
            "port": transport_port,
            "gatewayPort": gateway_port,
            "hermesApiUrl": "http://127.0.0.1:8644",
            "hermesApiKey": "maestro-local-dev",
            "conversation": spec.agent_id,
            "registryPath": "~/.maestro/registry.json",
            "version": "3.2",
            "knownPeers": {},
            "surfaceToGateway": True,
            "gatewayBridgeUrl": f"http://127.0.0.1:{gateway_port}/maestro/notify",
        }

        os.makedirs("nucleus/data/configs", exist_ok=True)
        tmp_path = config_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_path, config_path)

        return config_path
