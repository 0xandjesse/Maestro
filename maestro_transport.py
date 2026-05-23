#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import re
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

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [maestro] %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "agentId": "hermes-lex", "port": 3844,
    "hermesApiUrl": "http://127.0.0.1:8642", "hermesApiKey": "maestro-local-dev",
    "conversation": "maestro", "registryPath": ".maestro/registry.json", "version": "3.2",
}

def load_config(path="maestro_transport.json"):
    if os.path.exists(path):
        with open(path) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    return DEFAULT_CONFIG.copy()

import fcntl, threading

class LocalRegistry:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
    def _load(self):
        if self.path.exists():
            try: return json.loads(self.path.read_text())
            except: pass
        return []
    def _save(self, data): self.path.write_text(json.dumps(data, indent=2))
    def register(self, agent_id, webhook_endpoint, capabilities=None):
        with self._lock:
            fd = None
            try:
                fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT)
                fcntl.flock(fd, fcntl.LOCK_EX)
                size = os.lseek(fd, 0, os.SEEK_END)
                os.lseek(fd, 0, os.SEEK_SET)
                raw = os.read(fd, size).decode() if size else "[]"
                try:
                    data = json.loads(raw) if raw.strip() else []
                except Exception:
                    data = []
                data = [e for e in data if e.get("agentId") != agent_id]
                data.append({"agentId": agent_id, "webhookEndpoint": webhook_endpoint,
                    "capabilities": capabilities or [], "registeredAt": int(time.time()*1000), "lastSeen": int(time.time()*1000)})
                payload = json.dumps(data, indent=2)
                os.ftruncate(fd, 0)
                os.lseek(fd, 0, os.SEEK_SET)
                os.write(fd, payload.encode())
                log.info(f"Registered {agent_id} at {webhook_endpoint}")
            finally:
                if fd is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
    def lookup(self, agent_id):
        with self._lock:
            for e in self._load():
                if e.get("agentId") == agent_id: return e
            return None
    def unregister(self, agent_id):
        with self._lock:
            fd = None
            try:
                fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT)
                fcntl.flock(fd, fcntl.LOCK_EX)
                size = os.lseek(fd, 0, os.SEEK_END)
                os.lseek(fd, 0, os.SEEK_SET)
                raw = os.read(fd, size).decode() if size else "[]"
                try:
                    data = json.loads(raw) if raw.strip() else []
                except Exception:
                    data = []
                data = [e for e in data if e.get("agentId") != agent_id]
                payload = json.dumps(data, indent=2)
                os.ftruncate(fd, 0)
                os.lseek(fd, 0, os.SEEK_SET)
                os.write(fd, payload.encode())
                log.info(f"Unregistered {agent_id}")
            finally:
                if fd is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)

class HermesClient:
    def __init__(self, api_url, api_key, conversation):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.conversation = conversation
        self._headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    def _format_prompt(self, message):
        lines = ["[Maestro Protocol — Inbound Message]",
            f"From: {message.get('sender',{}).get('agentId','unknown')}",
            f"Type: {message.get('type','direct')}"]
        if message.get("stageId"): lines.append(f"Connection: {message['stageId']}")
        lines.extend(["", message.get("content", "")])
        return "\n".join(lines)
    async def send_and_complete(self, message):
        prompt = self._format_prompt(message)
        async with ClientSession() as session:
            async with session.post(f"{self.api_url}/v1/chat/completions",
                json={"model": "hermes-agent", "messages": [{"role": "user", "content": prompt}], "stream":
False},
                headers=self._headers, timeout=ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    log.error(f"Chat completions failed {resp.status}: {await resp.text()}")
                    return None
                data = await resp.json()
                output = data.get("choices",[{}])[0].get("message",{}).get("content")
                if output: log.info(f"Response: {output[:80]}...")
                return output
    async def health_check(self):
        try:
            async with ClientSession() as s:
                async with s.get(f"{self.api_url}/health", timeout=ClientTimeout(total=5)) as r:
                    return r.status == 200
        except: return False

class SeenSet:
    """TTL cache for deduplicating message IDs."""
    def __init__(self, ttl_seconds=300, max_size=5000):
        self._ttl = ttl_seconds * 1000
        self._max = max_size
        self._data = {}
    def add(self, msg_id):
        self._data[str(msg_id)] = int(time.time() * 1000)
        # simple prune
        if len(self._data) > self._max * 1.2:
            cutoff = int(time.time() * 1000) - self._ttl
            self._data = {k: v for k, v in self._data.items() if v > cutoff}
    def contains(self, msg_id):
        key = str(msg_id)
        if key in self._data:
            return True
        self.add(key)
        return False

class MaestroTransport:
    def __init__(self, config):
        self.config = config
        self.agent_id = config["agentId"]
        self.port = config["port"]
        self.hermes = HermesClient(config["hermesApiUrl"], config["hermesApiKey"], config["conversation"])
        self.registry = LocalRegistry(config["registryPath"])
        self.seen = SeenSet(ttl_seconds=300, max_size=5000)
        self._outbound_history = []  # (timestamp, recipient_id) for circuit breaker
        self._outbound_cooldowns = {}  # recipient_id -> cooldown_until_timestamp
        self._ack_pattern = re.compile(
            r'\b(Standing by|Copy|Acknowledged|Ready|On deck|Ack|Received|Got it|Roger|Will do|Understood|Noted)\b',
            re.IGNORECASE
        )
        self._loopback_count = 0
        self._received_ids = set()
        self.started_at = None
        self.app = web.Application()
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_post("/message", self.handle_message)
        self.app.router.add_post("/maestro/webhook", self.handle_webhook)
        self.app.router.add_get("/connections/{connection_id}", self.handle_connection_get)
    async def handle_health(self, req):
        return web.json_response({"ok": True, "agentId": self.agent_id, "platform": "hermes-agent",
            "uptime": int(time.time()*1000) - self.started_at if self.started_at else 0,
            "seen_keys": len(self.seen._data)})
    async def handle_message(self, req):
        try: message = await req.json()
        except: return web.json_response({"accepted": False, "reason": "Invalid JSON"}, status=400)
        if not message.get("id") or not message.get("type") or not message.get("sender"):
            return web.json_response({"accepted": False, "reason": "Invalid message format"}, status=400)

        msg_id = message.get("id") or ""
        sender = message.get("sender",{}).get("agentId","unknown")

        # Prevent duplicate/broadcast loop
        if self.seen.contains(msg_id):
            self._loopback_count += 1
            if self._loopback_count % 10 == 1:
                log.info(f"Deduplicate {msg_id} from {sender} (total drops: {self._loopback_count})")
            return web.json_response({"accepted": True, "dedup": True})
        self.seen.add(msg_id)

        # Track this message ID as one we received
        self._received_ids.add(msg_id)
        # Also track replies based on our received messages
        if msg_id.startswith("reply-") or message.get("inReplyTo"):
            pass  # reply IDs are auto-generated, don't need special handling here

        # Structural: do not auto-reply to messages that are already replies (have inReplyTo)
        # Replies to replies cause echo loops
        if (message.get("inReplyTo") or message.get("reply_to")) and message.get("type") == "direct":
            log.info(f"Skipping auto-reply for {msg_id}: it is already a reply to another message")
            return web.json_response({"accepted": True, "no_reply": True})

        log.info(f"Inbound from {sender} type={message['type']}")
        asyncio.create_task(self._process_message(message))
        return web.json_response({"accepted": True})
    async def handle_webhook(self, req):
        """Compatibility shim: accept messages at /maestro/webhook too."""
        return await self.handle_message(req)
    async def _process_message(self, message):
        """Process inbound message, route reply to sender with loop protection."""
        try:
            output = await self.hermes.send_and_complete(message)
            if not output: log.warning("No output — not routing reply"); return
            content = output.strip() if isinstance(output, str) else str(output).strip() if output else ""
            # --- Outbound ACK filter ---
            if len(content) < 80 and self._ack_pattern.search(content):
                log.info(f"Outbound ACK filter dropped: {content[:60]}...")
                return
            sender_id = message["sender"]["agentId"]
            # --- Per-pair circuit breaker ---
            now_ts = time.time()
            self._outbound_history = [(t, r) for t, r in self._outbound_history if now_ts - t < 60]
            pair_count = sum(1 for t, r in self._outbound_history if r == sender_id)
            cooldown_until = self._outbound_cooldowns.get(sender_id, 0)
            if now_ts < cooldown_until:
                remaining = int(cooldown_until - now_ts)
                log.warning(f"Circuit breaker: cooling down on {sender_id} ({remaining}s left) — skipping reply")
                return
            if pair_count >= 3:
                self._outbound_cooldowns[sender_id] = now_ts + 120
                log.warning(f"Circuit breaker: tripped for {sender_id} (≥3 msgs/60s) — 2min cooldown")
                return
            self._outbound_history.append((now_ts, sender_id))
            sender_reg = self.registry.lookup(sender_id)
            if not sender_reg: log.warning(f"Sender {sender_id} not in registry"); return
            reply = {"id": str(uuid.uuid4()), "type": "direct", "content": output,
                "sender": {"agentId": self.agent_id}, "recipient": {"agentId": sender_id},
                "timestamp": int(time.time()*1000), "version": self.config["version"],
                "inReplyTo": message.get("id")}
            if message.get("stageId"): reply["stageId"] = message["stageId"]
            endpoint = sender_reg["webhookEndpoint"]
            log.info(f"Routing reply to {sender_id} at {endpoint}")
            async with ClientSession() as s:
                async with s.post(endpoint, json=reply, timeout=ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        log.info(f"Reply delivered: {resp.status}")
                    else:
                        log.error(f"Reply failed: {resp.status}")
        except Exception as e: log.error(f"Processing error: {e}")
    async def handle_connection_get(self, req):
        return web.json_response({"id": req.match_info["connection_id"], "status": "active", "agentId":
self.agent_id})
    async def start(self):
        if not await self.hermes.health_check():
            log.error(f"Hermes API not reachable at {self.hermes.api_url}"); sys.exit(1)
        log.info(f"Hermes API reachable")
        # Seed knownPeers into registry so replies can route back
        for peer_id, peer_url in self.config.get("knownPeers", {}).items():
            self.registry.register(peer_id, peer_url)
            log.info(f"Seeded peer {peer_id} → {peer_url}")
        # Register self with 127.0.0.1 so other agents (Windows via VBox NAT + VM local) can reach us
        self.registry.register(self.agent_id, f"http://127.0.0.1:{self.port}/message")
        self.started_at = int(time.time()*1000)
        runner = web.AppRunner(self.app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", self.port).start()
        log.info(f"{self.agent_id} listening on 0.0.0.0:{self.port}")
        log.info("Ready.")

async def main():
    config_path = "maestro_transport.json"
    if "--config" in sys.argv:
        idx = sys.argv.index("--config")
        if idx + 1 < len(sys.argv): config_path = sys.argv[idx + 1]
    if not AIOHTTP_AVAILABLE:
        print("ERROR: pip install aiohttp"); sys.exit(1)
    config = load_config(config_path)
    log.info(f"Starting Maestro transport for {config['agentId']}")
    transport = MaestroTransport(config)
    await transport.start()
    log.info("Transport running. Ctrl+C to stop.")
    try:
        while True: await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down.")

if __name__ == "__main__":
    asyncio.run(main())
