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

    def generate_units(
        self,
        units_dir: str = "/home/andjesse/.config/systemd/user",
        transport_script: str = "/home/andjesse/Projects/Maestro/code/runtime/maestro_transport.py",
        configs_dir: str = "/home/andjesse/.maestro/configs",
        venv_python: str = "/home/andjesse/.hermes/hermes-agent/venv/bin/python",
        hermes_cli: str = "/home/andjesse/.hermes/hermes-agent/venv/bin/python",
        profiles_dir: str = "/home/andjesse/.hermes/profiles",
    ) -> dict[str, list[str]]:
        """Generate systemd unit files for all agents in the port map.

        Returns a dict of agent_id → list of generated unit file paths.
        """
        generated: dict[str, list[str]] = {}
        units_path = Path(units_dir)
        units_path.mkdir(parents=True, exist_ok=True)

        for agent_id in self._port_map.agents:
            assignment = self.resolve(agent_id)
            files: list[str] = []

            # ── Transport unit ──────────────────────────────────────
            transport_unit = units_path / f"maestro-transport-{agent_id}.service"
            transport_content = f"""[Unit]
Description=Maestro Transport — {agent_id}
After=network.target

[Service]
Type=simple
WorkingDirectory={Path(transport_script).parent}
ExecStart={venv_python} {transport_script} --config {configs_dir}/{agent_id}.json
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
            transport_unit.write_text(transport_content)
            files.append(str(transport_unit))

            # ── Gateway unit ────────────────────────────────────────
            gateway_unit = units_path / f"hermes-gateway-{agent_id}.service"
            profile_dir = f"{profiles_dir}/{agent_id}"
            gateway_content = f"""[Unit]
Description=Hermes Agent Gateway - Messaging Platform Integration
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart={hermes_cli} -m hermes_cli.main --profile {agent_id} gateway run
WorkingDirectory={profile_dir}
Environment="PATH={Path(venv_python).parent}:/home/andjesse/.hermes/hermes-agent/node_modules/.bin:/home/andjesse/.hermes/node/bin:/home/andjesse/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="VIRTUAL_ENV={Path(venv_python).parent.parent}"
Environment="HERMES_HOME={profile_dir}"
Restart=always
RestartSec=5
RestartForceExitStatus=75
KillMode=mixed
KillSignal=SIGTERM
ExecReload=/bin/kill -USR1 $MAINPID
ExecStopPost=-{venv_python} -m gateway.cgroup_cleanup
TimeoutStopSec=90
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""
            gateway_unit.write_text(gateway_content)
            files.append(str(gateway_unit))

            generated[agent_id] = files

        return generated

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
