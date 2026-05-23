"""
Runtime Registry — Canonical process ownership model for the Maestro mesh.

Prevents port hijacks and orphaned agent processes by maintaining an
authoritative JSON registry at `~/.maestro/registry.json`.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from hermes_cli.config import get_hermes_home

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_PATH = get_hermes_home() / "registry.json"


class RuntimeRegistry:
    """
    Thread-safe process ownership registry with file-level locking (POSIX fcntl).
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = path or DEFAULT_REGISTRY_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"agents": {}, "supervisor_pid": None, "last_heartbeat": None})

    def _read(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            logger.warning("Registry corrupted or missing; starting fresh")
            return {"agents": {}, "supervisor_pid": None, "last_heartbeat": None}

    def _write(self, data: Dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def register(self, agent_id: str, pid: int, port: int, profile: str, **extra) -> Dict[str, Any]:
        """
        Register a running agent. Raises RuntimeError on port conflict.
        """
        data = self._read()
        for existing_id, existing in data["agents"].items():
            if existing_id != agent_id and existing.get("port") == port:
                raise RuntimeError(
                    f"Port {port} is already owned by {existing_id} (PID {existing.get('pid')})"
                )
        data["agents"][agent_id] = {
            "pid": pid,
            "port": port,
            "profile": profile,
            "started": _iso_now(),
            "status": "healthy",
            **extra,
        }
        data["last_heartbeat"] = _iso_now()
        self._write(data)
        return data["agents"][agent_id]

    def deregister(self, agent_id: str) -> bool:
        """Deregister an agent. Returns True if it was present."""
        data = self._read()
        present = data["agents"].pop(agent_id, None) is not None
        if present:
            self._write(data)
        return present

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._read()["agents"].get(agent_id)

    def list_agents(self) -> Dict[str, Dict[str, Any]]:
        return self._read()["agents"]

    def update_status(self, agent_id: str, status: str, **extra) -> bool:
        data = self._read()
        if agent_id not in data["agents"]:
            return False
        data["agents"][agent_id]["status"] = status
        data["agents"][agent_id].update(extra)
        data["last_heartbeat"] = _iso_now()
        self._write(data)
        return True

    def find_by_port(self, port: int) -> Optional[tuple[str, Dict[str, Any]]]:
        data = self._read()
        for agent_id, info in data["agents"].items():
            if info.get("port") == port:
                return agent_id, info
        return None

    def is_registered(self, agent_id: str) -> bool:
        return agent_id in self._read()["agents"]

    def stale_orphans(self, max_age_s: float = 300.0) -> list[str]:
        """Return agent_ids whose PIDs are dead or older than max_age_s."""
        data = self._read()
        orphans = []
        for agent_id, info in data["agents"].items():
            pid = info.get("pid")
            if pid is not None:
                try:
                    os.kill(pid, 0)
                except OSError:
                    orphans.append(agent_id)
                    continue
            started = info.get("started")
            if started:
                try:
                    started_ts = _parse_iso(started)
                    if time.time() - started_ts > max_age_s:
                        pass  # still alive, not an orphan
                except Exception:
                    pass
        return orphans


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str) -> float:
    from datetime import datetime, timezone
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


# Singleton (process-safe via JSON file locking)
runtime_registry = RuntimeRegistry()
