#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import re
import sys
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    from aiohttp import web, ClientSession, ClientTimeout
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

# Optional: Google Calendar API for native trigger engine
CALENDAR_AVAILABLE = False
try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    CALENDAR_AVAILABLE = True
except ImportError:
    pass

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
                json={"model": "hermes-agent", "messages": [{"role": "user", "content": prompt}], "stream": False},
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

class CalendarWatcher:
    """Polls Google Calendar for trigger events and routes them as Maestro messages."""
    TO_TAG_RE = re.compile(r'^\[TO:\s*([^\]]+)\]\s*(.*)$', re.IGNORECASE | re.DOTALL)

    def __init__(self, credentials_path: str, calendar_id: str, transport, poll_interval: int = 60):
        self.credentials_path = Path(credentials_path)
        self.calendar_id = calendar_id
        self.transport = transport          # MaestroTransport instance
        self.poll_interval = poll_interval  # seconds between polls
        self._seen_event_ids = SeenSet(ttl_seconds=86400, max_size=5000)  # 24h dedup
        self._service = None
        self._credentials = None
        self._last_poll = None
        self._running = False

    def _load_credentials(self) -> Optional[Dict]:
        if not self.credentials_path.exists():
            log.error(f"CalendarWatcher: credentials not found at {self.credentials_path}")
            return None
        try:
            return json.loads(self.credentials_path.read_text())
        except Exception as e:
            log.error(f"CalendarWatcher: failed to load credentials: {e}")
            return None

    def _build_service(self):
        if not CALENDAR_AVAILABLE:
            log.error("CalendarWatcher: google-auth and google-api-python-client required: pip install google-auth google-api-python-client")
            return False
        creds_data = self._load_credentials()
        if not creds_data:
            return False
        try:
            self._credentials = Credentials(
                token=None,
                refresh_token=creds_data.get("refresh_token"),
                token_uri=creds_data.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=creds_data.get("client_id"),
                client_secret=creds_data.get("client_secret"),
                scopes=[creds_data.get("scope", "https://www.googleapis.com/auth/calendar")]
            )
            self._service = build("calendar", "v3", credentials=self._credentials, cache_discovery=False)
            return True
        except Exception as e:
            log.error(f"CalendarWatcher: failed to build service: {e}")
            return False

    def _parse_event(self, event: dict) -> Optional[Tuple[str, str, str]]:
        """Returns (recipient, content, event_id) or None if not a trigger."""
        summary = event.get("summary", "")
        description = event.get("description", "") or summary
        event_id = event.get("id", "")
        if not summary:
            return None
        # Check description for [TO:recipient] tag
        match = self.TO_TAG_RE.match(description.strip())
        if match:
            recipient = match.group(1).strip()
            content = match.group(2).strip()
            return (recipient, content, event_id)
        # Fallback: use summary if it has a [TO:] tag
        match = self.TO_TAG_RE.match(summary.strip())
        if match:
            recipient = match.group(1).strip()
            content = match.group(2).strip() or description.strip()
            return (recipient, content, event_id)
        return None

    async def _send_maestro_trigger(self, recipient: str, content: str, event_id: str, event_title: str):
        """Build and send a Maestro direct message."""
        msg = {
            "id": f"gcal-trigger-{event_id}-{int(time.time())}",
            "type": "direct",
            "sender": {"agentId": self.transport.agent_id},
            "recipient": recipient,
            "content": content,
            "meta": {
                "source": "calendar-trigger",
                "calendar_id": self.calendar_id,
                "event_id": event_id,
                "event_title": event_title,
                "triggered_at": datetime.now(timezone.utc).isoformat(),
            },
            "timestamp": int(time.time() * 1000),
            "version": self.transport.config.get("version", "3.2"),
        }
        # Dedup on message ID so we never double-fire
        if self.transport.seen.contains(msg["id"]):
            log.info(f"CalendarWatcher: already fired {msg['id']} — skipping")
            return
        self.transport.seen.add(msg["id"])

        if recipient == "broadcast" or recipient == "*":
            log.info(f"CalendarWatcher: firing broadcast for event '{event_title}'")
            await self.transport._broadcast_fanout(msg)
        else:
            entry = self.transport.registry.lookup(recipient)
            if not entry:
                log.error(f"CalendarWatcher: recipient '{recipient}' not in registry — cannot trigger")
                return
            endpoint = entry["webhookEndpoint"]
            log.info(f"CalendarWatcher: firing to {recipient} for '{event_title}' → {endpoint}")
            await self.transport._deliver(endpoint, msg)

    async def _poll_once(self):
        """Fetch recent events and fire triggers."""
        if not self._service:
            if not self._build_service():
                return

        # Look back 1 minute, forward 1 minute — generous window for missed events
        now = datetime.now(timezone.utc)
        time_min = (now - timedelta(minutes=1)).isoformat()
        time_max = (now + timedelta(minutes=1)).isoformat()

        try:
            events_result = self._service.events().list(
                calendarId=self.calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=10,
            ).execute()
            events = events_result.get("items", [])
            if events:
                log.info(f"CalendarWatcher: {len(events)} events in window")
            for event in events:
                event_id = event.get("id", "")
                if self._seen_event_ids.contains(event_id):
                    continue
                parsed = self._parse_event(event)
                if not parsed:
                    continue
                recipient, content, evt_id = parsed
                self._seen_event_ids.add(event_id)
                await self._send_maestro_trigger(recipient, content, evt_id, event.get("summary", ""))
        except Exception as e:
            log.error(f"CalendarWatcher: poll failed: {type(e).__name__}: {e}")

    async def run(self):
        if not CALENDAR_AVAILABLE:
            log.warning("CalendarWatcher: google-auth/google-api-python-client not installed. Calendar triggers disabled.")
            return
        if not self._build_service():
            log.error("CalendarWatcher: failed to initialize. Calendar triggers disabled.")
            return
        log.info(f"CalendarWatcher: initialized on calendar {self.calendar_id}")
        log.info(f"CalendarWatcher: polling every {self.poll_interval}s")
        self._running = True
        while self._running:
            try:
                await self._poll_once()
            except Exception as e:
                log.error(f"CalendarWatcher: exception in poll loop: {e}")
            await asyncio.sleep(self.poll_interval)

    def stop(self):
        self._running = False


class SeenSet:
    """TTL cache for deduplicating message IDs. Prevents broadcast loops."""
    def __init__(self, ttl_seconds=300, max_size=10000):
        self._seen = OrderedDict()
        self._ttl = ttl_seconds * 1000
        self._max_size = max_size
        self._lock = threading.Lock()

    def contains(self, msg_id):
        now = int(time.time() * 1000)
        # Normalize: dict → string key
        key = msg_id if isinstance(msg_id, str) else str(msg_id)
        with self._lock:
            # Expire old entries
            expired = [k for k, v in self._seen.items() if (now - v) > self._ttl]
            for k in expired:
                del self._seen[k]
            return key in self._seen

    def add(self, msg_id):
        now = int(time.time() * 1000)
        key = msg_id if isinstance(msg_id, str) else str(msg_id)
        with self._lock:
            if key in self._seen:
                return
            # Prune if oversized
            while len(self._seen) >= self._max_size:
                self._seen.popitem(last=False)
            self._seen[key] = now

class MaestroTransport:
    def __init__(self, config):
        self.config = config
        self.agent_id = config["agentId"]
        self.port = config["port"]
        self.hermes = HermesClient(config["hermesApiUrl"], config["hermesApiKey"], config["conversation"])
        self.registry = LocalRegistry(config["registryPath"])
        self.seen = SeenSet(ttl_seconds=300, max_size=10000)
        self.bb_root = Path("/home/andjesse/.maestro/blackboards")
        self.bb_root.mkdir(parents=True, exist_ok=True)
        self._loopback_count = 0  # diagnostic counter
        self.started_at = None
        self.app = web.Application()
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_post("/message", self.handle_message)
        self.app.router.add_post("/maestro/webhook", self.handle_webhook)
        self.app.router.add_get("/connections/{connection_id}", self.handle_connection_get)
        # Calendar trigger engine (opt-in via config)
        self.calendar_watcher = None
        self._setup_calendar_watcher(config)

    async def handle_health(self, req):
        return web.json_response({"ok": True, "agentId": self.agent_id, "platform": "hermes-agent",
            "uptime": int(time.time()*1000) - self.started_at if self.started_at else 0,
            "seen_keys": len(self.seen._seen)})

    async def handle_message(self, req):
        try: message = await req.json()
        except: return web.json_response({"accepted": False, "reason": "Invalid JSON"}, status=400)
        if not message.get("id") or not message.get("type") or not message.get("sender"):
            return web.json_response({"accepted": False, "reason": "Invalid message format"}, status=400)

        msg_id = message.get("id") or ""
        sender = message.get("sender",{}).get("agentId","?")
        msg_type = message.get("type")

        # Prevent duplicate/broadcast loop
        if self.seen.contains(msg_id):
            self._loopback_count += 1
            if self._loopback_count % 10 == 1:
                log.info(f"Deduplicate {msg_id} from {sender} (total drops: {self._loopback_count})")
            return web.json_response({"accepted": True, "dedup": True})
        self.seen.add(msg_id)

        log.info(f"Inbound from {sender} type={msg_type}")

        # Surface to gateway if configured
        if self.config.get("surfaceToGateway"):
            asyncio.create_task(self._surface_to_gateway(message))

        recipient = message.get("recipient")

        # BB ops
        if msg_type == "BB_WRITE":
            asyncio.create_task(self._process_bb_write(message))
            return web.json_response({"accepted": True})
        elif msg_type == "BB_READ":
            asyncio.create_task(self._process_bb_read(message))
            return web.json_response({"accepted": True})

        # Broadcast
        if recipient == "broadcast" or recipient == "*":
            asyncio.create_task(self._broadcast_fanout(message))

        # Standard P2P → Hermes
        asyncio.create_task(self._process_message(message))
        return web.json_response({"accepted": True})

    async def handle_webhook(self, req):
        """Compatibility shim: accept messages at /maestro/webhook too."""
        return await self.handle_message(req)

    # ----------------------------------------------------------
    # Blackboard
    # ----------------------------------------------------------

    def _get_bb_path(self, board_id: str) -> Path:
        return self.bb_root / f"{board_id}.json"

    async def _process_bb_write(self, message):
        board_id = message.get("boardId", "default")
        key = message.get("key")
        value = message.get("value")
        if not key:
            await self._route_system_reply(message, "Error: No key provided for blackboard write.")
            return
        bb_path = self._get_bb_path(board_id)
        data = {}
        if bb_path.exists():
            try: data = json.loads(bb_path.read_text())
            except: log.error(f"Failed to read {board_id}, starting fresh.")
        data[key] = {"value": value, "updatedBy": self.agent_id, "timestamp": int(time.time()*1000)}
        bb_path.write_text(json.dumps(data, indent=2))
        log.info(f"BB write: {key} on {board_id}")
        await self._route_system_reply(message, f"BB_WRITE OK: {key} on {board_id}")

    async def _process_bb_read(self, message):
        board_id = message.get("boardId", "default")
        key = message.get("key")
        bb_path = self._get_bb_path(board_id)
        if not bb_path.exists():
            await self._route_system_reply(message, f"Error: Blackboard {board_id} not found.")
            return
        try:
            data = json.loads(bb_path.read_text())
            if key:
                val = data.get(key)
                await self._route_system_reply(message, json.dumps(val, indent=2) if val else f"Key {key} not found in {board_id}.")
            else:
                await self._route_system_reply(message, json.dumps(data, indent=2))
        except Exception as e:
            await self._route_system_reply(message, f"Error reading blackboard: {type(e).__name__}: {e}")

    async def _route_system_reply(self, request_msg, content):
        sender_id = request_msg.get("sender",{}).get("agentId")
        if not sender_id:
            return
        sender_reg = self.registry.lookup(sender_id)
        if not sender_reg:
            log.warning(f"Sender {sender_id} not in registry — cannot route reply")
            return
        reply = {
            "id": str(uuid.uuid4()),
            "type": "direct",
            "content": content,
            "sender": {"agentId": self.agent_id},
            "recipient": sender_id,
            "timestamp": int(time.time()*1000),
            "version": self.config.get("version", "3.2"),
        }
        endpoint = sender_reg["webhookEndpoint"]
        log.info(f"System reply to {sender_id} at {endpoint}: {content[:60]}...")
        async with ClientSession() as s:
            try:
                async with s.post(endpoint, json=reply, timeout=ClientTimeout(total=10)) as resp:
                    log.info(f"System reply to {sender_id}: {resp.status}")
            except Exception as e:
                log.error(f"System reply failed to {sender_id} at {endpoint}: {type(e).__name__}: {e}")

    # ----------------------------------------------------------
    # Broadcast — fire-and-forget with dedup guard
    # ----------------------------------------------------------

    async def _broadcast_fanout(self, message):
        msg_id = message.get("id")
        log.info(f"Fanning out broadcast {msg_id} to peers")
        all_peers = self.registry._load()
        tasks = []
        for peer in all_peers:
            pid = peer.get("agentId", "")
            if pid == self.agent_id or not pid:
                continue
            endpoint = peer.get("webhookEndpoint")
            if not endpoint:
                continue
            tasks.append(self._deliver(endpoint, message))
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            ok = sum(1 for r in results if not isinstance(r, Exception))
            log.info(f"Broadcast {msg_id}: {ok}/{len(tasks)} delivered")

    async def _deliver(self, endpoint, message):
        async with ClientSession() as s:
            try:
                async with s.post(endpoint, json=message, timeout=ClientTimeout(total=10)) as resp:
                    log.debug(f"Deliver to {endpoint}: {resp.status}")
            except Exception as e:
                log.error(f"Deliver failed to {endpoint}: {type(e).__name__}: {e}")

    # ----------------------------------------------------------
    # Standard P2P → Hermes
    # ----------------------------------------------------------

    async def _process_message(self, message):
        try:
            log.debug(f"Forward to Hermes: {message.get('id')}")
            output = await self.hermes.send_and_complete(message)
            if not output:
                log.warning("No output from Hermes — not routing reply")
                return
            sender_id = message["sender"]["agentId"]
            sender_reg = self.registry.lookup(sender_id)
            if not sender_reg:
                log.warning(f"Sender {sender_id} not in registry")
                return
            reply = {
                "id": str(uuid.uuid4()),
                "type": "direct",
                "content": output,
                "sender": {"agentId": self.agent_id},
                "recipient": sender_id,
                "timestamp": int(time.time()*1000),
                "version": self.config["version"],
            }
            if message.get("stageId"):
                reply["stageId"] = message["stageId"]
            endpoint = sender_reg["webhookEndpoint"]
            log.info(f"Routing reply to {sender_id} at {endpoint}")
            async with ClientSession() as s:
                async with s.post(endpoint, json=reply, timeout=ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        log.info(f"Reply delivered: {resp.status}")
                    else:
                        log.error(f"Reply failed: {resp.status}")
        except Exception as e:
            log.error(f"Processing error: {type(e).__name__}: {e!r}")

    async def handle_connection_get(self, req):
        return web.json_response({"id": req.match_info["connection_id"], "status": "active", "agentId": self.agent_id})

    async def _surface_to_gateway(self, message: dict):
        """Post a lightweight notification to the gateway bridge for Telegram visibility."""
        bridge_url = self.config.get("gatewayBridgeUrl", "http://127.0.0.1:8644/maestro/notify")
        sender = message.get("sender", {}).get("agentId", "?")
        try:
            payload = {
                "agent_id": self.agent_id,
                "from": sender,
                "content": message.get("content", ""),
                "summary": message.get("content", "")[:200],
                "msg_type": message.get("type", "direct"),
            }
            async with ClientSession() as s:
                async with s.post(bridge_url, json=payload, timeout=ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        log.info(f"Surfaced to gateway: from {sender}")
                    else:
                        log.warning(f"Gateway surface failed: {resp.status}")
        except Exception as e:
            log.debug(f"Gateway surface skipped ({type(e).__name__}): {e}")

    def _setup_calendar_watcher(self, config):
        """Initialize calendar watcher if gcalCredentials and gcalCalendarId are in config."""
        gcal_creds = config.get("gcalCredentials")
        gcal_id = config.get("gcalCalendarId")
        if not gcal_creds or not gcal_id:
            log.info("CalendarWatcher: disabled (no gcalCredentials / gcalCalendarId in config)")
            return
        interval = config.get("gcalPollInterval", 60)
        self.calendar_watcher = CalendarWatcher(
            credentials_path=gcal_creds,
            calendar_id=gcal_id,
            transport=self,
            poll_interval=interval,
        )
        log.info(f"CalendarWatcher: configured on calendar {gcal_id} (poll {interval}s)")

    async def start(self):
        if not await self.hermes.health_check():
            log.error(f"Hermes API not reachable at {self.hermes.api_url}"); sys.exit(1)
        log.info(f"Hermes API reachable")
        for peer_id, peer_url in self.config.get("knownPeers", {}).items():
            self.registry.register(peer_id, peer_url)
            log.info(f"Seeded peer {peer_id} → {peer_url}")
        self.registry.register(self.agent_id, f"http://127.0.0.1:{self.port}/message")
        self.started_at = int(time.time()*1000)
        runner = web.AppRunner(self.app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", self.port).start()
        log.info(f"{self.agent_id} listening on 0.0.0.0:{self.port}")
        log.info("Ready.")
        log.info("Features: dedup, BB_WRITE, BB_READ, broadcast, /message, /maestro/webhook, /health, /connections, calendar-triggers")
        # Start calendar watcher in background if configured
        if self.calendar_watcher:
            asyncio.create_task(self.calendar_watcher.run())
            log.info(f"CalendarWatcher: background poll started")
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            log.info("Shutting down.")
            if self.calendar_watcher:
                self.calendar_watcher.stop()

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
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down.")

if __name__ == "__main__":
    asyncio.run(main())
