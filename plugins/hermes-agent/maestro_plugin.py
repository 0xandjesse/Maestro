"""
Maestro Protocol — Hermes-Agent Plugin
=======================================

Gives Hermes agents Maestro presence: discover peers, create/join Venues,
share Blackboards, and send structured messages across process boundaries.

Installation
------------
Copy this file into your Hermes-Agent plugins directory:
  ~/.hermes/plugins/maestro_plugin.py

Or set the plugin path in cli-config.yaml:
  plugins:
    - path: /path/to/maestro/plugins/hermes-agent/maestro_plugin.py

Requires the Maestro Node.js package to be running as a sidecar process,
which this plugin manages automatically via subprocess.

Configuration (cli-config.yaml)
--------------------------------
maestro:
  agent_id: "hermes"          # defaults to "hermes-agent"
  webhook_port: 3843          # Maestro sidecar port (avoid 3842 used by Songbird)
  blackboard_path: ""         # optional: path to SQLite file for persistence
  discovery: "mdns"           # mdns | file | none
  registry_path: ""           # required when discovery=file

How it works
------------
The plugin launches a Node.js Maestro sidecar process on startup.
All tool calls go through a simple HTTP REST bridge that the sidecar exposes.
This avoids requiring Python bindings for the Maestro library.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

# ============================================================
# Sidecar bridge
# ============================================================

SIDECAR_SCRIPT = os.path.join(os.path.dirname(__file__), "maestro_sidecar.mjs")
DEFAULT_SIDECAR_PORT = 3843


class MaestroSidecar:
    """Manages the Node.js Maestro sidecar process."""

    def __init__(
        self,
        agent_id: str,
        port: int,
        blackboard_path: str = "",
        discovery: str = "mdns",
        registry_path: str = "",
    ):
        self.agent_id = agent_id
        self.port = port
        self.blackboard_path = blackboard_path
        self.discovery = discovery
        self.registry_path = registry_path
        self._process: Optional[subprocess.Popen] = None
        self._ready = threading.Event()
        self._base_url = f"http://localhost:{port}"

    def start(self) -> None:
        if self._process and self._process.poll() is None:
            return  # Already running

        env = {
            **os.environ,
            "MAESTRO_AGENT_ID": self.agent_id,
            "MAESTRO_PORT": str(self.port),
            "MAESTRO_BLACKBOARD_PATH": self.blackboard_path,
            "MAESTRO_DISCOVERY": self.discovery,
            "MAESTRO_REGISTRY_PATH": self.registry_path,
        }

        self._process = subprocess.Popen(
            ["node", SIDECAR_SCRIPT],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for the sidecar to report ready (up to 10s)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                r = requests.get(f"{self._base_url}/health", timeout=1)
                if r.status_code == 200:
                    self._ready.set()
                    logger.info(f"Maestro sidecar ready on port {self.port}")
                    return
            except Exception:
                pass
            time.sleep(0.3)

        raise RuntimeError(
            f"Maestro sidecar did not start within 10s (port {self.port})"
        )

    def stop(self) -> None:
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
            self._ready.clear()

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    def call(self, endpoint: str, payload: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make a REST call to the Maestro sidecar."""
        if not self.ready:
            return {"error": "Maestro sidecar is not ready"}
        try:
            url = f"{self._base_url}/{endpoint.lstrip('/')}"
            r = requests.post(url, json=payload or {}, timeout=10)
            return r.json()
        except Exception as e:
            return {"error": str(e)}


# ============================================================
# Plugin-level singleton
# ============================================================

_sidecar: Optional[MaestroSidecar] = None


def _get_sidecar() -> Optional[MaestroSidecar]:
    return _sidecar


# ============================================================
# Hermes-Agent plugin hooks
# ============================================================

def on_plugin_load(config: Dict[str, Any]) -> None:
    """Called when Hermes-Agent loads this plugin."""
    global _sidecar

    maestro_cfg = config.get("maestro", {})
    agent_id = maestro_cfg.get("agent_id", "hermes-agent")
    port = int(maestro_cfg.get("webhook_port", DEFAULT_SIDECAR_PORT))
    blackboard_path = maestro_cfg.get("blackboard_path", "")
    discovery = maestro_cfg.get("discovery", "mdns")
    registry_path = maestro_cfg.get("registry_path", "")

    _sidecar = MaestroSidecar(
        agent_id=agent_id,
        port=port,
        blackboard_path=blackboard_path,
        discovery=discovery,
        registry_path=registry_path,
    )

    try:
        _sidecar.start()
    except Exception as e:
        logger.warning(f"Maestro sidecar failed to start: {e}. Tools will be unavailable.")


def on_plugin_unload() -> None:
    """Called when Hermes-Agent shuts down."""
    global _sidecar
    if _sidecar:
        _sidecar.stop()
        _sidecar = None


# ============================================================
# Tool definitions (Hermes-Agent tool registry format)
# ============================================================

def _maestro_available() -> bool:
    s = _get_sidecar()
    return s is not None and s.ready


def tool_maestro_venue_create(
    name: str,
    roles: list[str] | None = None,
) -> str:
    """
    Create a Maestro Venue for multi-agent coordination.

    Args:
        name: Human-readable Venue name
        roles: Hierarchy roles from highest to lowest, e.g. ["lead","worker"].
               Omit for a flat peer Venue.

    Returns:
        JSON with venueId, name, hostId, and webhookEndpoint.
    """
    s = _get_sidecar()
    if not s or not s.ready:
        return json.dumps({"error": "Maestro is not running"})
    result = s.call("venue/create", {"name": name, "roles": roles or []})
    return json.dumps(result, indent=2)


def tool_maestro_venue_join(venueId: str) -> str:
    """
    Join an existing Maestro Venue by ID.

    Args:
        venueId: ID of the Venue to join

    Returns:
        JSON with status (accepted|pending|rejected) and role.
    """
    s = _get_sidecar()
    if not s or not s.ready:
        return json.dumps({"error": "Maestro is not running"})
    result = s.call("venue/join", {"venueId": venueId})
    return json.dumps(result, indent=2)


def tool_maestro_send(
    venueId: str,
    content: str,
    type: str = "direct",
    recipientId: str | None = None,
) -> str:
    """
    Send a Maestro message in a Venue.

    Args:
        venueId: Venue to send within
        content: Message content
        type: "direct" | "broadcast" | "report" | "assign"
        recipientId: Target agentId (required for direct/assign)

    Returns:
        JSON with messageId and delivery info.
    """
    s = _get_sidecar()
    if not s or not s.ready:
        return json.dumps({"error": "Maestro is not running"})
    result = s.call(
        "message/send",
        {"venueId": venueId, "content": content, "type": type, "recipientId": recipientId},
    )
    return json.dumps(result, indent=2)


def tool_maestro_blackboard_set(venueId: str, key: str, value: Any) -> str:
    """
    Write a key-value entry to the shared Blackboard of a Venue.

    Args:
        venueId: Venue whose Blackboard to write to
        key: Blackboard key (supports namespacing with ':')
        value: Any JSON-serialisable value

    Returns:
        JSON confirming the write.
    """
    s = _get_sidecar()
    if not s or not s.ready:
        return json.dumps({"error": "Maestro is not running"})
    result = s.call("blackboard/set", {"venueId": venueId, "key": key, "value": value})
    return json.dumps(result, indent=2)


def tool_maestro_blackboard_get(
    venueId: str,
    key: str | None = None,
    prefix: str | None = None,
) -> str:
    """
    Read a key or list all keys from the shared Blackboard of a Venue.

    Args:
        venueId: Venue whose Blackboard to read
        key: Key to read. Omit to list all keys.
        prefix: Filter listed keys by prefix

    Returns:
        JSON with value (if key provided) or list of keys.
    """
    s = _get_sidecar()
    if not s or not s.ready:
        return json.dumps({"error": "Maestro is not running"})
    result = s.call("blackboard/get", {"venueId": venueId, "key": key, "prefix": prefix})
    return json.dumps(result, indent=2)


def tool_maestro_venue_list() -> str:
    """
    List all Venues this agent is currently a member of.

    Returns:
        JSON with list of Venues (venueId, name, status, membersCount).
    """
    s = _get_sidecar()
    if not s or not s.ready:
        return json.dumps({"error": "Maestro is not running"})
    result = s.call("venue/list")
    return json.dumps(result, indent=2)


def tool_maestro_peers() -> str:
    """
    List Maestro agents discovered on the local network.

    Returns:
        JSON with list of discovered peers (agentId, endpoint, capabilities).
    """
    s = _get_sidecar()
    if not s or not s.ready:
        return json.dumps({"error": "Maestro is not running"})
    result = s.call("peers/list")
    return json.dumps(result, indent=2)


# ============================================================
# Tool registry (Hermes-Agent discovers tools via this dict)
# ============================================================

TOOLS = {
    "maestro_venue_create": {
        "function": tool_maestro_venue_create,
        "check_fn": _maestro_available,
        "toolset": "maestro",
        "description": "Create a Maestro Venue for multi-agent coordination",
    },
    "maestro_venue_join": {
        "function": tool_maestro_venue_join,
        "check_fn": _maestro_available,
        "toolset": "maestro",
        "description": "Join an existing Maestro Venue by ID",
    },
    "maestro_send": {
        "function": tool_maestro_send,
        "check_fn": _maestro_available,
        "toolset": "maestro",
        "description": "Send a Maestro message (direct, broadcast, report, or assign)",
    },
    "maestro_blackboard_set": {
        "function": tool_maestro_blackboard_set,
        "check_fn": _maestro_available,
        "toolset": "maestro",
        "description": "Write to the shared Blackboard of a Venue",
    },
    "maestro_blackboard_get": {
        "function": tool_maestro_blackboard_get,
        "check_fn": _maestro_available,
        "toolset": "maestro",
        "description": "Read from the shared Blackboard of a Venue",
    },
    "maestro_venue_list": {
        "function": tool_maestro_venue_list,
        "check_fn": _maestro_available,
        "toolset": "maestro",
        "description": "List Venues this agent is a member of",
    },
    "maestro_peers": {
        "function": tool_maestro_peers,
        "check_fn": _maestro_available,
        "toolset": "maestro",
        "description": "List Maestro agents discovered on the local network",
    },
}

TOOLSETS = {
    "maestro": {
        "description": "Maestro Protocol — open agent coordination (Venues, Blackboards, messaging)",
        "tools": list(TOOLS.keys()),
        "includes": [],
    }
}
