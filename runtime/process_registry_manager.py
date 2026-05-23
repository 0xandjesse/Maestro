"""
Authoritative runtime process registry with supervisor heartbeat.

Maintains ~/.maestro/registry.json:
  { "agents": { ... }, "supervisor_pid": pid, "last_heartbeat": "ISO8601" }

On startup:
  - Detect port conflicts before binding
  - Register PID+port+profile+timestamp
  - Launch supervisor heartbeat cron (every 60s)

On shutdown (best-effort):
  - Deregister self
  - Write state to registry

Provides CLI read API used by `maestro status`.
"""
import json
import os
import platform
import signal
import socket
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

import asyncio
from dataclasses import dataclass, asdict

logger = None  # set lazily


REGISTRY_PATH = Path.home() / ".maestro" / "registry.json"
AGENT_STATUS_HEALTHY = "healthy"
AGENT_STATUS_STALE = "stale"
AGENT_STATUS_ORPHANED = "orphaned"

HEARTBEAT_INTERVAL_S = 60
HEARTBEAT_STALE_THRESHOLD_S = 180


def _require_logger():
    global logger
    if logger is None:
        import logging
        logger = logging.getLogger("process_registry")
    return logger


def _load_registry() -> Dict[str, Any]:
    if REGISTRY_PATH.exists():
        try:
            return json.loads(REGISTRY_PATH.read_text())
        except Exception:
            pass
    return {"agents": {}, "supervisor_pid": None, "last_heartbeat": None}


def _save_registry(data: Dict[str, Any]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        REGISTRY_PATH.write_text(json.dumps(data, indent=2, default=str))
    except Exception as e:
        _require_logger().warning("Failed to write registry: %s", e)


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def check_port_conflict(port: int, agent_id: str) -> Optional[str]:
    """Return error string if the port is already owned by another agent."""
    reg = _load_registry()
    for aid, info in reg.get("agents", {}).items():
        if aid == agent_id:
            continue
        if info.get("port") == port:
            owner_pid = info.get("pid")
            if owner_pid and _pid_alive(owner_pid):
                return f"Port {port} is already owned by {aid} (PID {owner_pid}). Use a different port."
            # Dead owner — stale entry, clean it up
            info["status"] = AGENT_STATUS_ORPHANED
    return None


def register_agent(agent_id: str, port: int, profile: str, pid: int = None, session_key: str = None) -> None:
    """Register this agent in the authoritative registry."""
    reg = _load_registry()
    reg.setdefault("agents", {})
    reg["agents"][agent_id] = {
        "pid": pid or os.getpid(),
        "port": port,
        "profile": profile,
        "started": datetime.now(timezone.utc).isoformat(),
        "status": AGENT_STATUS_HEALTHY,
        "session_key": session_key or "",
    }
    reg["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
    _save_registry(reg)
    _require_logger().info("Registered agent %s @ port %d (pid=%s)", agent_id, port, reg["agents"][agent_id]["pid"])


def deregister_agent(agent_id: str) -> None:
    reg = _load_registry()
    if agent_id in reg.get("agents", {}):
        del reg["agents"][agent_id]
        _save_registry(reg)
        _require_logger().info("Deregistered agent %s", agent_id)


def get_registry() -> Dict[str, Any]:
    return _load_registry()


def list_agents() -> List[Dict[str, Any]]:
    reg = _load_registry()
    out = []
    for aid, info in reg.get("agents", {}).items():
        info = dict(info)
        info["agent_id"] = aid
        info["pid_alive"] = _pid_alive(info.get("pid", 0))
        out.append(info)
    return out


def mark_agent_status(agent_id: str, status: str) -> None:
    reg = _load_registry()
    if agent_id in reg.get("agents", {}):
        reg["agents"][agent_id]["status"] = status
        _save_registry(reg)


# ---------------------------------------------------------------------------
# Supervisor heartbeat loop (background asyncio task)
# ---------------------------------------------------------------------------

async def supervisor_heartbeat_task(
    agent_id: str,
    port: int,
    profile: str,
    interval: float = HEARTBEAT_INTERVAL_S,
):
    """Background task: heartbeat + stale detection."""
    _require_logger().info("Supervisor heartbeat started for %s", agent_id)
    while True:
        try:
            self_pid = os.getpid()
            if not _pid_alive(self_pid):
                return  # should never happen
            reg = _load_registry()
            reg["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
            reg["supervisor_pid"] = self_pid
            # Check all peers for staleness
            for aid, info in reg.get("agents", {}).items():
                if aid == agent_id:
                    continue
                if not _pid_alive(info.get("pid", 0)):
                    info["status"] = AGENT_STATUS_ORPHANED
                # If last heartbeat stale -> mark stale
            _save_registry(reg)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception as e:
            _require_logger().warning("Supervisor heartbeat error: %s", e)
            await asyncio.sleep(interval)


def cleanup_orphans(agent_id: str = None) -> None:
    """Walk registry and SIGTERM→SIGKILL all orphaned processes."""
    reg = _load_registry()
    removed = []
    for aid, info in list(reg.get("agents", {}).items()):
        if aid == agent_id:
            continue
        status = info.get("status", "")
        pid = info.get("pid")
        alive = False
        if pid:
            try:
                os.kill(pid, 0)
                alive = True
            except (OSError, ProcessLookupError):
                pass
        if status == AGENT_STATUS_ORPHANED or (not alive and pid):
            if alive and pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                    time.sleep(2)
                    try:
                        os.kill(pid, 0)
                        os.kill(pid, signal.SIGKILL)
                        time.sleep(0.5)
                    except (OSError, ProcessLookupError):
                        pass
                except (OSError, ProcessLookupError):
                    pass
            removed.append({"agent_id": aid, "pid": pid, "status": status})
            del reg["agents"][aid]
    if removed:
        _save_registry(reg)
        _require_logger().warning("governed_orphan_cleanup: removed %d orphans", len(removed))
        try:
            import sys, pathlib
            sys.path.insert(0, str(pathlib.Path(__file__).parent))
            from audit_log import write as _audit_write, EVENT_GOVERNED_ORPHAN_CLEANUP
            _audit_write(EVENT_GOVERNED_ORPHAN_CLEANUP, {"removed": removed})
        except Exception:
            pass


def register_orphan_cleanup_handler() -> None:
    """Register atexit handler for orphan cleanup. Best-effort only."""
    try:
        import atexit
        atexit.register(cleanup_orphans, agent_id=None)
    except Exception:
        pass


def resolve_agent_port_conflict(port: int, agent_id: str) -> Optional[str]:
    """Public entry for conflict resolution."""
    return check_port_conflict(port, agent_id)
