#!/usr/bin/env python3
"""
Maestro Protocol — Hermes-Agent Transport (Python)
===================================================
Gives a Hermes-Agent instance a native Maestro identity.

Runs as a sidecar alongside the Hermes gateway. Listens for
inbound MaestroMessages, delivers them to Hermes via the API
server (/v1/runs), streams the SSE response, and POSTs the
reply back to the original sender's /message endpoint.

This makes Hermes-Agent a full Maestro peer — not a target
accessed via a proxy, but a first-class participant that can:
  - Receive direct messages from any Maestro agent
  - Open Connections and participate in shared Blackboards
  - Be discovered via mDNS or registry
  - Route replies back as MaestroMessages

Usage:
    python maestro_transport.py [--config maestro_transport.json]

Config (maestro_transport.json):
    {
        "agentId": "hermes-lex",
        "port": 3844,
        "hermesApiUrl": "http://127.0.0.1:8642",
        "hermesApiKey": "maestro-local-dev",
        "conversation": "maestro",
        "registryPath": ".maestro/registry.json"
    }
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from aiohttp import web, ClientSession, ClientTimeout
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [maestro] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger(__name__)

# ----------------------------------------------------------
# Config
# ----------------------------------------------------------

DEFAULT_CONFIG = {
    "agentId": "hermes-lex",
    "port": 3844,
    "hermesApiUrl": "http://127.0.0.1:8642",
    "hermesApiKey": "maestro-local-dev",
    "conversation": "maestro",
    "registryPath": ".maestro/registry.json",
    "version": "3.2",
    # knownPeers: static peer endpoints, seeded into registry on startup.
    # Key format: { "agentId": "endpoint" }
    # Use this for cross-host peers that can't be discovered via mDNS.
    "knownPeers": {},
}

def load_config(path: str = "maestro_transport.json") -> Dict[str, Any]:
    if os.path.exists(path):
        with open(path) as f:
            cfg = json.load(f)
        return {**DEFAULT_CONFIG, **cfg}
    return DEFAULT_CONFIG.copy()


# ----------------------------------------------------------
# Registry (file-based, compatible with JS LocalRegistry)
# ----------------------------------------------------------

class LocalRegistry:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                pass
        return []

    def _save(self, data: list):
        self.path.write_text(json.dumps(data, indent=2))

    def register(self, agent_id: str, webhook_endpoint: str, capabilities: list = None):
        data = self._load()
        # Remove existing entry for this agent if present
        data = [e for e in data if e.get("agentId") != agent_id]
        entry = {
            "agentId": agent_id,
            "webhookEndpoint": webhook_endpoint,
            "capabilities": capabilities or [],
            "registeredAt": int(time.time() * 1000),
            "lastSeen": int(time.time() * 1000),
        }
        data.append(entry)
        self._save(data)
        log.info(f"Registered {agent_id} at {webhook_endpoint}")

    def lookup(self, agent_id: str) -> Optional[Dict[str, Any]]:
        for entry in self._load():
            if entry.get("agentId") == agent_id:
                return entry
        return None

    def unregister(self, agent_id: str):
        data = self._load()
        data = [e for e in data if e.get("agentId") != agent_id]
        self._save(data)


# ----------------------------------------------------------
# Hermes API client
# ----------------------------------------------------------

class HermesClient:
    def __init__(self, api_url: str, api_key: str, conversation: str):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.conversation = conversation
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    def _format_prompt(self, message: Dict[str, Any]) -> str:
        lines = [
            "[Maestro Protocol — Inbound Message]",
            f"From: {message.get('sender', {}).get('agentId', 'unknown')}",
            f"Type: {message.get('type', 'direct')}",
        ]
        if message.get("stageId"):
            lines.append(f"Connection: {message['stageId']}")
        lines.append("")
        lines.append(message.get("content", ""))
        return "\n".join(lines)

    async def send_and_complete(self, message: Dict[str, Any]) -> Optional[str]:
        """Send a message to Hermes via chat completions (non-streaming). Returns the output text."""
        prompt = self._format_prompt(message)

        async with ClientSession() as session:
            timeout = ClientTimeout(total=120)
            async with session.post(
                f"{self.api_url}/v1/chat/completions",
                json={
                    "model": "hermes-agent",
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                headers=self._headers,
                timeout=timeout,
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    log.error(f"Chat completions failed {resp.status}: {text}")
                    return None
                data = await resp.json()
                output = data.get("choices", [{}])[0].get("message", {}).get("content")
                if output:
                    log.info(f"Response received: {output[:80]}...")
                return output

    async def health_check(self) -> bool:
        try:
            async with ClientSession() as session:
                async with session.get(
                    f"{self.api_url}/health",
                    timeout=ClientTimeout(total=5),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False


# ----------------------------------------------------------
# Maestro Transport HTTP Server
# ----------------------------------------------------------

class MaestroTransport:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.agent_id = config["agentId"]
        self.port = config["port"]
        self.hermes = HermesClient(
            config["hermesApiUrl"],
            config["hermesApiKey"],
            config["conversation"],
        )
        self.registry = LocalRegistry(config["registryPath"])
        self.started_at = None
        self.app = web.Application()
        self._setup_routes()

    WEBHOOK_PATH = "/maestro/webhook"

    def _setup_routes(self):
        self.app.router.add_get("/health", self.handle_health)
        # Accept both paths for backward compatibility
        self.app.router.add_post("/maestro/webhook", self.handle_message)
        self.app.router.add_post("/message", self.handle_message)
        self.app.router.add_get("/connections/{connection_id}", self.handle_connection_get)

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "ok": True,
            "agentId": self.agent_id,
            "platform": "hermes-agent",
            "uptime": int(time.time() * 1000) - self.started_at if self.started_at else 0,
        })

    async def handle_message(self, request: web.Request) -> web.Response:
        try:
            message = await request.json()
        except Exception:
            return web.json_response({"accepted": False, "reason": "Invalid JSON"}, status=400)

        if not message.get("id") or not message.get("type") or not message.get("sender"):
            return web.json_response({"accepted": False, "reason": "Invalid message format"}, status=400)

        log.info(f"Inbound message from {message['sender'].get('agentId')} type={message['type']}")

        # Accept immediately, process async
        asyncio.create_task(self._process_message(message))
        return web.json_response({"accepted": True})

    async def _process_message(self, message: Dict[str, Any]):
        """Process an inbound message: send to Hermes, route reply back."""
        try:
            output = await self.hermes.send_and_complete(message)
            if not output:
                log.warning("No output from Hermes — not routing reply")
                return

            sender_id = message["sender"]["agentId"]
            sender_reg = self.registry.lookup(sender_id)
            if not sender_reg:
                log.warning(f"Sender {sender_id} not in registry — cannot route reply")
                return

            reply = {
                "id": str(uuid.uuid4()),
                "type": "direct",
                "content": output,
                "sender": {"agentId": self.agent_id},
                "recipient": sender_id,
                "timestamp": int(time.time() * 1000),
                "version": self.config["version"],
            }
            if message.get("stageId"):
                reply["stageId"] = message["stageId"]

            endpoint = sender_reg["webhookEndpoint"]
            log.info(f"Routing reply to {sender_id} at {endpoint}: {output[:80]}...")

            async with ClientSession() as session:
                async with session.post(
                    endpoint,
                    json=reply,
                    timeout=ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        log.info(f"Reply delivered to {sender_id}")
                    else:
                        log.error(f"Reply delivery failed: {resp.status}")

        except Exception as e:
            log.error(f"Message processing error: {e}")

    async def handle_connection_get(self, request: web.Request) -> web.Response:
        # Stub — full Connection support coming in a future version
        connection_id = request.match_info["connection_id"]
        return web.json_response({
            "id": connection_id,
            "status": "active",
            "agentId": self.agent_id,
        })

    async def start(self):
        # Health check Hermes API
        ok = await self.hermes.health_check()
        if not ok:
            log.error(f"Hermes API not reachable at {self.hermes.api_url} — is the gateway running?")
            sys.exit(1)
        log.info(f"Hermes API reachable at {self.hermes.api_url}")

        # Register in local registry — use /maestro/webhook to match Node plugin standard
        # Use 0.0.0.0 for VM-side registration; Windows host accesses via port forward
        endpoint = f"http://0.0.0.0:{self.port}/maestro/webhook"
        self.registry.register(self.agent_id, endpoint)

        # Seed known peers into registry (static cross-host endpoints)
        known_peers = self.config.get("knownPeers", {})
        for peer_id, peer_endpoint in known_peers.items():
            self.registry.register(peer_id, peer_endpoint)
            log.info(f"Seeded known peer: {peer_id} at {peer_endpoint}")

        self.started_at = int(time.time() * 1000)
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.port)
        await site.start()
        log.info(f"{self.agent_id} listening on 0.0.0.0:{self.port}")
        log.info(f"Hermes API: {self.hermes.api_url}")
        log.info(f"Conversation: {self.hermes.conversation}")
        log.info("Ready.")


# ----------------------------------------------------------
# Entry point
# ----------------------------------------------------------

async def main():
    config_path = "maestro_transport.json"
    if "--config" in sys.argv:
        idx = sys.argv.index("--config")
        if idx + 1 < len(sys.argv):
            config_path = sys.argv[idx + 1]

    if not AIOHTTP_AVAILABLE:
        print("ERROR: aiohttp is required. Install with: pip install aiohttp")
        sys.exit(1)

    config = load_config(config_path)
    log.info(f"Starting Maestro transport for {config['agentId']}")

    transport = MaestroTransport(config)
    await transport.start()

    # Keep running
    log.info("Transport running. Press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down.")


if __name__ == "__main__":
    asyncio.run(main())
