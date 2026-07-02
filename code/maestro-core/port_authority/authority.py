# nucleus/modules/port_authority/authority.py
"""Port Authority — single source of truth for port assignments."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .interface import PortAssignment, PortAuthority
from .schema import PortMap


class FilePortAuthority(PortAuthority):
    """File-backed port authority with runtime verification."""

    def __init__(self, port_map_path: str = "/home/andjesse/Projects/Maestro/nucleus/data/port_map.json") -> None:
        self._path = Path(port_map_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._port_map = self._load()

    # ── public API ─────────────────────────────────────────────────

    def resolve(self, agent_id: str) -> PortAssignment:
        """Look up an agent's port assignment. Raises KeyError if not found."""
        agent_ports = self._port_map.agents.get(agent_id)
        if agent_ports is None:
            raise KeyError(f"Agent '{agent_id}' not found in port map")
        return PortAssignment(
            agent_id=agent_id,
            transport_port=agent_ports["transport_port"],
            gateway_port=agent_ports["gateway_port"],
        )

    def assign(self, agent_id: str, transport_port: int, gateway_port: int) -> PortAssignment:
        """Assign ports to an agent and persist."""
        self._port_map.agents[agent_id] = {
            "transport_port": transport_port,
            "gateway_port": gateway_port,
        }
        self._port_map.last_updated = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._save()
        return PortAssignment(agent_id=agent_id, transport_port=transport_port, gateway_port=gateway_port)

    def verify(self) -> tuple[bool, list[str]]:
        """Check that all assigned ports match actual listening ports.

        Returns (all_ok, list_of_errors).
        """
        errors: list[str] = []
        listening = self._get_listening_ports()

        for agent_id, ports in self._port_map.agents.items():
            tp = ports["transport_port"]
            if tp not in listening:
                errors.append(f"{agent_id}: transport port {tp} is NOT listening")
            gp = ports["gateway_port"]
            if gp not in listening:
                errors.append(f"{agent_id}: gateway port {gp} is NOT listening")

        # Check bridge port
        bridge_port = self._port_map.bridge.get("port")
        if bridge_port and bridge_port not in listening:
            errors.append(f"bridge: port {bridge_port} is NOT listening")

        return (len(errors) == 0, errors)

    def list_all(self) -> list[PortAssignment]:
        """Return all port assignments."""
        return [
            PortAssignment(
                agent_id=aid,
                transport_port=p["transport_port"],
                gateway_port=p["gateway_port"],
            )
            for aid, p in self._port_map.agents.items()
        ]

    def is_port_available(self, port: int) -> bool:
        """Check if a port is free (not in use by any process)."""
        listening = self._get_listening_ports()
        return port not in listening

    # ── internal ───────────────────────────────────────────────────

    def _load(self) -> PortMap:
        """Load port map from disk, or return empty default."""
        if not self._path.exists():
            return PortMap()

        # Try the nucleus path first, fall back to legacy ~/.maestro/port_map.json
        raw = self._path.read_text()
        if not raw.strip():
            return PortMap()

        data = json.loads(raw)
        return PortMap.from_dict(data)

    def _save(self) -> None:
        """Atomically write port map to disk."""
        payload = json.dumps(self._port_map.to_dict(), indent=2)
        tmp_path = str(self._path) + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_path, str(self._path))

    @staticmethod
    def _get_listening_ports() -> set[int]:
        """Return the set of ports currently in LISTEN state."""
        try:
            result = subprocess.run(
                ["ss", "-tlnp", "-H"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            ports: set[int] = set()
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    # Format: "LISTEN 0 128 0.0.0.0:3842 ..."
                    addr = parts[3]
                    if ":" in addr:
                        try:
                            port = int(addr.rsplit(":", 1)[-1])
                            ports.add(port)
                        except ValueError:
                            pass
            return ports
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return set()
