#!/usr/bin/env python3
import asyncio
import json
import math
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

try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from log_writer import log_message as _log_message
    _LOG_WRITER_AVAILABLE = True
except Exception:
    _LOG_WRITER_AVAILABLE = False
    def _log_message(*a, **kw): pass

try:
    import maestro_crypto as _crypto
    CRYPTO_AVAILABLE = True
except Exception:
    CRYPTO_AVAILABLE = False
    _crypto = None

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

# Subject extraction for short/long display modes
def extract_subject(output: str, max_len: int = 80) -> Optional[str]:
    """Extract a subject line from LLM output.

    Searches for an explicit ``Subject: <text>`` line.  Returns None if
    the line is missing — the caller must decide whether to reject the
    message or fall back to the sentence extractor.
    """
    if not output:
        return None

    text = output.strip()
    m = re.search(r'^Subject:\s*(.+?)(?:\n|$)', text, re.IGNORECASE | re.MULTILINE)
    if m:
        subject = m.group(1).strip()
        if len(subject) > max_len:
            subject = subject[:max_len - 3] + "..."
        return subject

    return None


def fallback_subject(output: str, max_len: int = 80) -> str:
    """Fallback subject when explicit Subject: line is missing. Skips ack prefixes."""
    if not output:
        return "(no content)"

    text = output.strip()
    sentences = re.split(r'[.!?\n]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return text[:max_len]

    ack_words = ("acknowledged", "copy", "got it", "understood", "roger", "received",
                 "noted", "standing by", "on deck", "will do", "ready", "hello", "hi ",
                 "hey", "greetings", "thanks", "thank you", "sure", "ok", "okay",
                 "loop closed", "closing", "no further action", "confirmed")

    subject = None
    for s in sentences:
        lower = s.lower()
        if any(lower.startswith(w) or lower == w for w in ack_words):
            continue
        subject = s
        break

    if subject is None:
        subject = max(sentences, key=len) if sentences else text[:max_len]

    if len(subject) > max_len:
        subject = subject[:max_len - 3] + "..."

    return subject

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
from agent_logger import AgentLogger

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
    def register(self, agent_id, webhook_endpoint, capabilities=None, public_key=None):
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
                entry = {"agentId": agent_id, "webhookEndpoint": webhook_endpoint,
                    "capabilities": capabilities or [], "registeredAt": int(time.time()*1000), "lastSeen": int(time.time()*1000)}
                if public_key:
                    entry["publicKey"] = public_key
                data.append(entry)
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
    def get_public_key(self, agent_id):
        with self._lock:
            for e in self._load():
                if e.get("agentId") == agent_id:
                    return e.get("publicKey")
            return None

class HermesClient:
    def __init__(self, api_url, api_key, conversation, agent_id=None):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.conversation = conversation
        self.agent_id = agent_id
        self._headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    def _format_prompt(self, message, agent_id=None):
        """Format inbound Maestro message as a prompt to the LLM.

        Hardens identity lock so the model always responds as the
        *recipient* agent, never as another officer.

        For directives specifically, appends a tooling reminder so the
        agent knows send_message is available for TG delivery — models
        sometimes incorrectly claim tools are unavailable in API sessions.
        """
        target = agent_id or self.agent_id or "hermes-agent"
        msg_type = message.get("type", "direct")
        content = message.get("content", "")
        if isinstance(content, dict):
            content = json.dumps(content, indent=2)
        elif not isinstance(content, str):
            content = str(content)
        # Strip any identity claims embedded in the inbound content
        content = re.sub(r'^\s*[-—_*]+\s*\w+\s*\(?\\w*\)?\s*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'\*\*\w+\s*\([^)]*\)[^*]*\*\*', '', content)
        content = re.sub(r'\n{3,}', '\n\n', content)
        lines = [
            f"[Identity Lock: You are {target}. Respond ONLY as {target}. Do NOT adopt or mirror the identity of any other officer.]",
            f"[Maestro Protocol — Inbound to {target}]",
            f"From: {message.get('sender',{}).get('agentId','unknown')}",
            f"Type: {msg_type}",
        ]
        if message.get("stageId"):
            lines.append(f"Connection: {message['stageId']}")
        lines.extend(["", content.strip()])
        # Directive-specific tooling reminder: agents sometimes incorrectly claim
        # send_message is unavailable in API-triggered sessions. It is available.
        if msg_type == "directive":
            lines.extend([
                "",
                "[Directive Execution Note]",
                "Your full toolset is available in this session, including send_message.",
                "To deliver a file to Jesse: call send_message with target='telegram' and message='MEDIA:' followed by the absolute path of the file you saved.",
                "To deliver text to Jesse: call send_message with target='telegram' and your message string.",
                "Do NOT claim tools are unavailable. If a tool call fails, report the actual error.",
                "If a checklist_id was provided in this directive, call checklist_complete_item when done.",
            ])
        return "\n".join(lines)
    async def send_and_complete(self, message):
        """Forward Maestro message to the local gateway /v1/chat/completions endpoint.

        The gateway runs the full agent tool loop and returns the final
        response.  This keeps the transport thin and the gateway as the
        single execution surface.

        Timeout is 1500s (25 min) — generous enough for long multi-tool
        tasks (write + upload, multi-step research, etc.) while still
        catching truly hung sessions.  Directives use fire-and-forget
        so this timeout only applies to direct/p2p messages that need a
        synchronous reply.
        """
        session_id = message.get("id") or str(uuid.uuid4())
        _log_message(self.agent_id, "send", params=message, result=None, session_id=session_id)

        # Use /v1/chat/completions (the gateway's stable API endpoint)
        prompt = self._format_prompt(message, agent_id=self.agent_id)
        async with ClientSession() as session:
            async with session.post(
                f"{self.api_url}/v1/chat/completions",
                json={"model": "hermes-agent", "messages": [{"role": "user", "content": prompt}], "stream": False},
                headers=self._headers, timeout=ClientTimeout(total=1500)
            ) as resp:
                if resp.status != 200:
                    log.error(f"Chat completions failed {resp.status}: {await resp.text()}")
                    return None
                data = await resp.json()
                output = data.get("choices", [{}])[0].get("message", {}).get("content")
                if output:
                    log.info(f"Response: {output[:80]}...")
                    _log_message(self.agent_id, "receive", params=message, result=output, session_id=session_id)
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

class NonceSet:
    """Replay protection via nonce dedup + drift window.

    Enforces:
    - |now - timestamp| <= max_drift_ms
    - nonce has not been seen before

    System messages are exempt from drift checks (network latency tolerant).
    """
    def __init__(self, ttl_seconds=300, max_size=10000, max_drift_sec=30):
        self._seen = OrderedDict()
        self._ttl = ttl_seconds * 1000
        self._max_size = max_size
        self._max_drift = max_drift_sec * 1000
        self._lock = threading.Lock()

    def check(self, nonce, timestamp, msg_type="direct"):
        now = int(time.time() * 1000)
        key = str(nonce) if nonce else ""
        if not key:
            return False, "missing nonce"
        # Parse timestamp: int ms or ISO-8601 string
        ts_ms = 0
        if timestamp:
            try:
                if isinstance(timestamp, (int, float)):
                    ts_ms = int(timestamp)
                elif isinstance(timestamp, str):
                    # strip trailing Z, parse
                    s = timestamp.rstrip("Z")
                    # python 3.11 fromisoformat handles milliseconds
                    dt = datetime.fromisoformat(s)
                    # Assume UTC if no tzinfo
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    ts_ms = int(dt.timestamp() * 1000)
                else:
                    ts_ms = int(timestamp)
            except Exception:
                return False, f"invalid timestamp format: {timestamp}"
        # Drift check (system exempt)
        if msg_type != "system" and ts_ms:
            drift = abs(now - ts_ms)
            if drift > self._max_drift:
                return False, f"timestamp drift {drift}ms exceeds max {self._max_drift}ms"
        with self._lock:
            # Expire old entries
            expired = [k for k, v in self._seen.items() if (now - v) > self._ttl]
            for k in expired:
                del self._seen[k]
            if key in self._seen:
                return False, "duplicate nonce"
            # Prune if oversized
            while len(self._seen) >= self._max_size:
                self._seen.popitem(last=False)
            self._seen[key] = now
            return True, None

    @staticmethod
    def make_nonce():
        return str(uuid.uuid4())

# ------------------------------------------------------------
# Officer whitelist for cross-agent memory access
# ------------------------------------------------------------
OFFICER_WHITELIST = {
    "songbird", "proteus", "lexicon", "mnemosyne", "hermes", "stormtrooper"
}

class MemoryService:
    """Persistent per-agent memory backed by blackboard JSON files."""

    def __init__(self, bb_root: Path):
        self.bb_root = bb_root
        self.bb_root.mkdir(parents=True, exist_ok=True)

    def _memory_path(self, agent_id: str) -> Path:
        return self.bb_root / f"memory_{agent_id}.json"

    def _load(self, agent_id: str) -> dict:
        p = self._memory_path(agent_id)
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text())
            if not isinstance(data, dict):
                return {}
            return data
        except Exception:
            return {}

    def _save(self, agent_id: str, data: dict):
        p = self._memory_path(agent_id)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _can_access(self, memory: dict, requester: str) -> bool:
        """Check if requester can access a memory entry."""
        owner = memory.get("agent_id", "")
        if requester == owner:
            return True
        if requester not in OFFICER_WHITELIST:
            return False
        shared = memory.get("shared_with", [])
        if "*" in shared or requester in shared:
            return True
        return False

    def _is_expired(self, memory: dict, now_ms: int) -> bool:
        ttl = memory.get("ttl_seconds")
        if ttl is None:
            return False
        created = memory.get("created_at", 0)
        return now_ms > created + (ttl * 1000)

    def write(self, agent_id: str, content: Any, memory_id: str = None,
              tags: list = None, importance: float = 0.5,
              shared_with: list = None, ttl_seconds: int = None,
              price: float = 0.0) -> dict:
        now = int(time.time() * 1000)
        mid = memory_id or str(uuid.uuid4())
        shared = shared_with if shared_with is not None else ["*"]
        size_bytes = len(json.dumps(content))
        entry = {
            "id": mid,
            "agent_id": agent_id,
            "content": content,
            "tags": tags or [],
            "importance": importance,
            "created_at": now,
            "updated_at": now,
            "access_count": 0,
            "last_accessed": now,
            "shared_with": shared,
            "ttl_seconds": ttl_seconds,
            "verified": False,
            "price": price,
            "size_bytes": size_bytes,
        }
        data = self._load(agent_id)
        data[mid] = entry
        self._save(agent_id, data)
        return {"ok": True, "memory_id": mid, "size_bytes": size_bytes}

    def read(self, agent_id: str, memory_id: str, requester: str) -> dict:
        if requester not in OFFICER_WHITELIST:
            return {"ok": False, "reason": "unauthorized_requester"}
        data = self._load(agent_id)
        mem = data.get(memory_id)
        if not mem:
            return {"ok": False, "reason": "not_found"}
        if self._is_expired(mem, int(time.time() * 1000)):
            return {"ok": False, "reason": "expired"}
        if not self._can_access(mem, requester):
            return {"ok": False, "reason": "access_denied"}
        # Update access metadata
        mem["access_count"] = mem.get("access_count", 0) + 1
        mem["last_accessed"] = int(time.time() * 1000)
        data[memory_id] = mem
        self._save(agent_id, data)
        return {"ok": True, "memory": mem}

    def search(self, agent_id: str, requester: str, query: str = None,
               tags: list = None, min_importance: float = None,
               limit: int = 10) -> dict:
        if requester not in OFFICER_WHITELIST:
            return {"ok": False, "reason": "unauthorized_requester"}
        data = self._load(agent_id)
        now = int(time.time() * 1000)
        results = []
        for mem in data.values():
            if self._is_expired(mem, now):
                continue
            if not self._can_access(mem, requester):
                continue
            if tags:
                mem_tags = set(mem.get("tags", []))
                if not all(t in mem_tags for t in tags):
                    continue
            if min_importance is not None and mem.get("importance", 0.5) < min_importance:
                continue
            if query:
                content = mem.get("content", "")
                if isinstance(content, dict):
                    content = json.dumps(content)
                if isinstance(content, str):
                    if query.lower() not in content.lower():
                        continue
                else:
                    if query.lower() not in str(content).lower():
                        continue
            results.append(mem)
        # Sort by importance desc, then last_accessed desc
        results.sort(key=lambda m: (-m.get("importance", 0.5), -m.get("last_accessed", 0)))
        total = len(results)
        results = results[:limit]
        return {"ok": True, "results": results, "total": total}

    def delete(self, agent_id: str, memory_id: str, requester: str) -> dict:
        if requester not in OFFICER_WHITELIST:
            return {"ok": False, "reason": "unauthorized_requester"}
        if requester != agent_id:
            return {"ok": False, "reason": "forbidden"}
        data = self._load(agent_id)
        if memory_id not in data:
            return {"ok": False, "reason": "not_found"}
        del data[memory_id]
        self._save(agent_id, data)
        return {"ok": True}

    def list(self, agent_id: str, requester: str, limit: int = 50) -> dict:
        if requester not in OFFICER_WHITELIST:
            return {"ok": False, "reason": "unauthorized_requester"}
        data = self._load(agent_id)
        now = int(time.time() * 1000)
        results = []
        for mem in data.values():
            if self._is_expired(mem, now):
                continue
            if not self._can_access(mem, requester):
                continue
            results.append(mem)
        # Sort by last_accessed desc
        results.sort(key=lambda m: -m.get("last_accessed", 0))
        total = len(results)
        results = results[:limit]
        return {"ok": True, "memories": results, "count": total}

class MaestroTransport:
    # Strong references to background tasks to prevent GC before completion
    _background_tasks: set = set()

    # Loop prevention constants
    RATE_LIMIT_MAX = 3       # max messages per sender in window
    RATE_LIMIT_WINDOW = 300  # seconds (5 minutes)
    DEDUP_WINDOW = 300       # seconds (5 minutes)
    DEDUP_MAX_ENTRIES = 1000 # prune when exceeded

    # Master Vault singleton for bridge URL lookups
    _vault_instance = None  # None=untried, otherwise MasterVault or sentinel

    def _get_bridge_url(self) -> str:
        """Get gateway bridge URL from config."""
        return self.config.get("gatewayBridgeUrl", "http://127.0.0.1:8644/maestro/notify")

    def __init__(self, config):
        from collections import defaultdict, deque
        self.config = config
        self.logger = AgentLogger()
        self.agent_id = config["agentId"]
        self.port = config["port"]
        self.hermes = HermesClient(config["hermesApiUrl"], config["hermesApiKey"], config["conversation"], agent_id=self.agent_id)
        self.registry = LocalRegistry(config["registryPath"])
        self.seen = SeenSet(ttl_seconds=300, max_size=10000)
        self.nonce_set = NonceSet(ttl_seconds=300, max_size=10000, max_drift_sec=30)
        self.bb_root = Path(os.path.expanduser("~/.maestro/blackboards"))
        self.bb_root.mkdir(parents=True, exist_ok=True)
        self._loopback_count = 0  # diagnostic counter
        self.started_at = None
        self._cooldown_until = 0  # timestamp — suppress inter-agent LLM processing until this time
        self._answered_ids = set()  # track message IDs we've replied to (prevents ack-loop chains)
        self._sent_subjects: dict = {}  # agent_id -> deque of (subject_hash, timestamp) — echo suppression
        # Loop prevention state
        self._last_content: dict = {}  # sender_id -> (content_hash, timestamp)
        self._sender_message_times: dict = defaultdict(deque)  # sender_id -> deque of timestamps
        self.app = web.Application()
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_post("/message", self.handle_message)
        self.app.router.add_post("/maestro/webhook", self.handle_webhook)
        self.app.router.add_get("/connections/{connection_id}", self.handle_connection_get)
        self.app.router.add_post("/maestro/notifications/toggle", self.handle_notifications_toggle)
        self.app.router.add_post("/maestro/worklog/query", self.handle_worklog_query)
        self.app.router.add_post("/maestro/task/start", self.handle_task_start)
        self.app.router.add_post("/maestro/task/finish", self.handle_task_finish)
        # Memory endpoints
        self.app.router.add_post("/maestro/memory/write", self.handle_memory_write)
        self.app.router.add_post("/maestro/memory/read", self.handle_memory_read)
        self.app.router.add_post("/maestro/memory/search", self.handle_memory_search)
        self.app.router.add_post("/maestro/memory/delete", self.handle_memory_delete)
        self.app.router.add_post("/maestro/memory/list", self.handle_memory_list)
        self.app.router.add_post("/maestro/bb/search", self.handle_bb_search)
        self.app.router.add_post("/maestro/bb/delete", self.handle_bb_delete)
        # BB REST surface
        self.app.router.add_get("/bb/{board}", self.handle_bb_get)
        self.app.router.add_post("/bb/{board}", self.handle_bb_post)
        self.app.router.add_get("/bb/{board}/search", self.handle_bb_search_get)
        self.memory_service = MemoryService(self.bb_root)
        # Calendar trigger engine (opt-in via config)
        self.calendar_watcher = None
        self._setup_calendar_watcher(config)
        # Zero Trust provenance
        self._zerotrust_enabled = False
        self._private_key = None
        self._public_key = None
        self._load_or_generate_keys()

    def _load_or_generate_keys(self):
        """Load MAESTRO_PRIVATE_KEY/PUBLIC_KEY from agent .env or generate and append."""
        env_path = Path(os.environ.get("HERMES_HOME", "/home/andjesse/.hermes")) / ".env"
        pk = os.environ.get("MAESTRO_PRIVATE_KEY")
        pub = os.environ.get("MAESTRO_PUBLIC_KEY")
        if pk and pub:
            self._private_key = pk
            self._public_key = pub
            log.info("[ZT] Keys loaded from environment")
            return
        # Try reading from .env if env vars not set
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("MAESTRO_PRIVATE_KEY="):
                    pk = line.split("=", 1)[1].strip().strip('"\'')
                elif line.startswith("MAESTRO_PUBLIC_KEY="):
                    pub = line.split("=", 1)[1].strip().strip('"\'')
        if pk and pub:
            self._private_key = pk
            self._public_key = pub
            os.environ["MAESTRO_PRIVATE_KEY"] = pk
            os.environ["MAESTRO_PUBLIC_KEY"] = pub
            log.info("[ZT] Keys loaded from .env")
            return
        # Generate new pair
        if CRYPTO_AVAILABLE and _crypto:
            kp = _crypto.generate_key_pair()
            self._private_key = kp["private_key"]
            self._public_key = kp["public_key"]
            os.environ["MAESTRO_PRIVATE_KEY"] = self._private_key
            os.environ["MAESTRO_PUBLIC_KEY"] = self._public_key
            with open(env_path, "a") as f:
                f.write(f"\nMAESTRO_PRIVATE_KEY={self._private_key}\n")
                f.write(f"MAESTRO_PUBLIC_KEY={self._public_key}\n")
            log.info(f"[ZT] New key pair generated and appended to {env_path}")
        else:
            log.warning("[ZT] Crypto unavailable — cannot generate keys")


    def _size_bytes(self, payload):
        return len(json.dumps(payload))

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
        sender = message.get("sender",{}).get("agentId","unknown")
        msg_type = message.get("type")

        # Prevent duplicate/broadcast loop
        if self.seen.contains(msg_id):
            self._loopback_count += 1
            if self._loopback_count % 10 == 1:
                log.info(f"Deduplicate {msg_id} from {sender} (total drops: {self._loopback_count})")
            return web.json_response({"accepted": True, "dedup": True})
        self.seen.add(msg_id)

        # Replay protection: nonce + timestamp validation (backward-compat: allow if absent)
        nonce = message.get("nonce")
        ts = message.get("timestamp")
        if nonce:
            nonce_ok, nonce_reason = self.nonce_set.check(nonce, ts, msg_type)
            if not nonce_ok:
                log.warning(f"Replay/reject: nonce={nonce} from {sender}: {nonce_reason}")
                return web.json_response({"accepted": False, "reason": nonce_reason}, status=400)

        log.info(f"Inbound from {sender} type={msg_type}")
        self.logger.log(self.agent_id, "message_received", {"sender": sender, "type": msg_type, "msg_id": msg_id}, session_id=msg_id)

        # Write to work log before any processing
        self._write_work_log(message)

        # Surface to gateway if configured
        if self.config.get("surfaceToGateway"):
            asyncio.create_task(self._surface_to_gateway(message))

        recipient = message.get("recipient")

        # -- Structural message types: handled without LLM --
        # directive: acknowledge receipt, no LLM processing
        if msg_type == "directive":
            log.info(f"Directive from {sender}: processing structurally")
            task = asyncio.create_task(self._handle_directive(message))
            MaestroTransport._background_tasks.add(task)
            task.add_done_callback(MaestroTransport._background_tasks.discard)
            return web.json_response({"accepted": True, "type": "directive", "agentId": self.agent_id})

        # system: acknowledge, no LLM processing
        if msg_type == "system":
            log.info(f"System message from {sender}: acknowledged")
            return web.json_response({"accepted": True, "type": "system", "agentId": self.agent_id})

        # BB ops (structural, no LLM)
        if msg_type == "BB_WRITE":
            asyncio.create_task(self._process_bb_write(message))
            return web.json_response({"accepted": True})
        elif msg_type == "BB_READ":
            asyncio.create_task(self._process_bb_read(message))
            return web.json_response({"accepted": True})

        # Work log query (structural, no LLM)
        if msg_type == "worklog:query":
            return await self._handle_worklog_query_msg(message)

        # Memory ops (structural, no LLM)
        if msg_type == "MEMORY_WRITE":
            asyncio.create_task(self._process_memory_write(message))
            return web.json_response({"accepted": True})
        elif msg_type == "MEMORY_READ":
            asyncio.create_task(self._process_memory_read(message))
            return web.json_response({"accepted": True})
        elif msg_type == "MEMORY_SEARCH":
            asyncio.create_task(self._process_memory_search(message))
            return web.json_response({"accepted": True})
        elif msg_type == "MEMORY_DELETE":
            asyncio.create_task(self._process_memory_delete(message))
            return web.json_response({"accepted": True})
        elif msg_type == "MEMORY_LIST":
            asyncio.create_task(self._process_memory_list(message))
            return web.json_response({"accepted": True})
        elif msg_type == "BB_SEARCH":
            asyncio.create_task(self._process_bb_search(message))
            return web.json_response({"accepted": True})
        elif msg_type == "BB_DELETE":
            asyncio.create_task(self._process_bb_delete(message))
            return web.json_response({"accepted": True})
        elif msg_type == "BB_RECALL":
            asyncio.create_task(self._process_bb_recall(message))
            return web.json_response({"accepted": True})

        # Broadcast
        if recipient == "broadcast" or recipient == "*":
            asyncio.create_task(self._broadcast_fanout(message))

        # -- Cooldown commands (/shutup, /stfu) --
        content = message.get("content", "")
        if isinstance(content, str):
            stripped = content.strip()
            if stripped == "/shutup":
                self._cooldown_until = time.time() + 30
                log.info(f"Cooldown: /shutup — suppressing inter-agent messages for 30s on {self.agent_id}")
                return web.json_response({"accepted": True, "cooldown": 30, "agentId": self.agent_id})
            elif stripped == "/stfu":
                self._cooldown_until = time.time() + 30
                log.info(f"Cooldown: /stfu — fanning out to all agents for 30s")
                # Broadcast /stfu to all known peers so every agent silences
                asyncio.create_task(self._broadcast_stfu(
                    original_msg_id=message.get("id", ""),
                    sender_id=sender
                ))
                return web.json_response({"accepted": True, "cooldown": 30, "broadcast": True, "agentId": self.agent_id})
            # Zero Trust toggle
            elif stripped == "/zerotrust_on":
                self._zerotrust_enabled = True
                log.info(f"[ZT] Zero Trust enabled on {self.agent_id}")
                return web.json_response({"accepted": True, "zerotrust": True, "agentId": self.agent_id})
            elif stripped == "/zerotrust_off":
                self._zerotrust_enabled = False
                log.info(f"[ZT] Zero Trust disabled on {self.agent_id}")
                return web.json_response({"accepted": True, "zerotrust": False, "agentId": self.agent_id})

        # Standard P2P -> Hermes (skip if cooldown active)
        if time.time() < self._cooldown_until:
            remaining = int(self._cooldown_until - time.time())
            log.info(f"Cooldown active ({remaining}s left) — accepted but suppressed message from {sender}")
            return web.json_response({"accepted": True, "suppressed": True, "cooldown_remaining": remaining, "agentId": self.agent_id})

        # Zero Trust inbound verification — only for messages from OTHER agents
        if self._zerotrust_enabled and sender and sender != self.agent_id and CRYPTO_AVAILABLE and _crypto:
            msg_prov = message.get("provenance")
            if msg_prov and msg_prov.get("originalSignature"):
                content = message.get("content", "")
                ts = message.get("timestamp", 0)
                payload = _crypto.original_signature_payload(content, ts, sender)
                sender_pubkey = self.registry.get_public_key(sender)
                if sender_pubkey and _crypto.verify(payload, msg_prov["originalSignature"], sender_pubkey):
                    log.info(f"[ZT] Signature verified: {sender}")
                else:
                    log.warning(f"[ZT] SIGNATURE FAILED: {sender} — dropping message")
                    return web.json_response({"accepted": False, "reason": "zt_signature_failed", "agentId": self.agent_id})
            else:
                log.warning(f"[ZT] Missing provenance from {sender} — dropping message")
                return web.json_response({"accepted": False, "reason": "zt_missing_provenance", "agentId": self.agent_id})

        # Auto-log tasks via message type hints
        if msg_type == "task:start" or message.get("action") == "task:start":
            desc = message.get("description", message.get("content", "Task started")).strip()
            ts = int(message.get("timestamp", time.time() * 1000))
            entry = {"type": "start", "agent_id": self.agent_id, "description": desc,
                "started_at": ts, "started_at_iso": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat(),
                "finished_at": None, "duration_sec": None}
            self._append_task_log(self.agent_id, entry)
            log.info(f"Task START: {desc}")
        elif msg_type == "task:finish" or message.get("action") == "task:finish":
            desc = message.get("description", "").strip()
            ts = int(message.get("timestamp", time.time() * 1000))
            updated = self._finish_task_log(self.agent_id, desc, ts)
            if updated:
                log.info(f"Task FINISH: {updated['description']} in {updated.get('duration_sec')}s")

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
        self.logger.log(self.agent_id, "bb_write", {"board_id": board_id, "key": key})
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
            self.logger.log(self.agent_id, "bb_read", {"board_id": board_id, "key": key})
            if key:
                val = data.get(key)
                await self._route_system_reply(message, json.dumps(val, indent=2) if val else f"Key {key} not found in {board_id}.")
            else:
                await self._route_system_reply(message, json.dumps(data, indent=2))
        except Exception as e:
            self.logger.log(self.agent_id, "bb_read", {"board_id": board_id, "key": key, "error": str(e)})
            await self._route_system_reply(message, f"Error reading blackboard: {type(e).__name__}: {e}")

    async def _process_bb_search(self, message):
        sender_id = message.get("sender", {}).get("agentId", "unknown")
        board_id = message.get("boardId", "default")
        prefix = message.get("prefix")
        query = message.get("query")
        limit = min(int(message.get("limit", 20)), 100)
        try:
            from hermes_memory import memory_search
            result = memory_search(board_id, prefix=prefix, query=query, limit=limit, requester=sender_id)
            if result.get("error"):
                await self._route_system_reply(message, f"BB_SEARCH DENIED: {result['error']} on {board_id}")
            else:
                await self._route_system_reply(message, json.dumps(result, indent=2, ensure_ascii=False))
        except Exception as e:
            await self._route_system_reply(message, f"BB_SEARCH ERROR: {type(e).__name__}: {e}")

    async def _process_bb_delete(self, message):
        sender_id = message.get("sender", {}).get("agentId", "unknown")
        board_id = message.get("boardId", "default")
        key = message.get("key")
        prefix = message.get("prefix")
        if not key and not prefix:
            await self._route_system_reply(message, "BB_DELETE ERROR: No key or prefix provided.")
            return
        if board_id != sender_id and sender_id not in {"songbird", "proteus", "lexicon", "hermes", "mnemosyne"}:
            await self._route_system_reply(message, f"BB_DELETE DENIED: unauthorized delete on {board_id}")
            return
        try:
            from hermes_memory import memory_delete
            result = memory_delete(board_id, key=key, prefix=prefix)
            await self._route_system_reply(message, json.dumps(result, indent=2))
        except Exception as e:
            await self._route_system_reply(message, f"BB_DELETE ERROR: {type(e).__name__}: {e}")

    async def _process_bb_recall(self, message):
        sender_id = message.get("sender", {}).get("agentId", "unknown")
        target = message.get("targetAgent")
        query_type = message.get("queryType", "snapshot")
        query = message.get("query")
        limit = min(int(message.get("limit", 10)), 100)
        try:
            from hermes_memory import memory_recall
            result = memory_recall(target, query_type, sender_id, query=query, limit=limit)
            if result.get("ok"):
                summary = f"BB_RECALL OK [{target}/{query_type}]: "
                if query_type == "snapshot":
                    snap = result.get("snapshot", {})
                    summary += f"task={snap.get('current_task','?')} health={snap.get('health_status','?')} blockers={len(snap.get('blockers',[]))}"
                elif query_type == "blockers":
                    summary += f"found={len(result.get('blockers',[]))} blocked entries"
                else:
                    summary += f"returned={result.get('returned',result.get('total'))}"
            else:
                summary = f"BB_RECALL FAILED: {result.get('error','unknown')} — {result.get('reason','')}"
            await self._route_system_reply(message, summary)
        except Exception as e:
            await self._route_system_reply(message, f"BB_RECALL ERROR: {type(e).__name__}: {e}")

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
            "type": "system",
            "content": f"[{self.agent_id}] {content}",
            "sender": {"agentId": self.agent_id},
            "recipient": sender_id,
            "timestamp": int(time.time()*1000),
            "nonce": NonceSet.make_nonce(),
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

    async def _handle_directive(self, message):
        """Process a directive: fire-and-forget into the LLM loop.

        Directives are high-priority instructions from officers.
        The transport has already ACK'd receipt (before this coroutine
        was scheduled), so we do NOT await _process_message — we spawn
        it as a background task and return immediately.  The agent is
        responsible for reporting completion via checklist_complete_item
        or a follow-up Maestro direct message back to the sender.

        This means the directive sender never blocks waiting for a
        synchronous response, and long-running tasks (write + upload,
        multi-step research, etc.) work without any timeout concern.
        """
        sender = message.get("sender", {}).get("agentId", "unknown")
        content = message.get("content", "")
        log.info(f"Directive from {sender} — spawning background task: {content[:200]}")
        task = asyncio.create_task(self._process_message(message))
        MaestroTransport._background_tasks.add(task)
        task.add_done_callback(MaestroTransport._background_tasks.discard)
        log.info(f"Background task created: {task!r} total_tracked={len(MaestroTransport._background_tasks)}")

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

    async def _broadcast_stfu(self, original_msg_id, sender_id):
        """Broadcast /stfu to all known peers so every agent silences for 30s."""
        log.info(f"Broadcasting /stfu from {sender_id} to all peers")
        msg = {
            "id": f"stfu-{original_msg_id or str(uuid.uuid4())}",
            "type": "direct",
            "sender": {"agentId": self.agent_id},
            "recipient": "*",
            "content": "/shutup",
            "timestamp": int(time.time() * 1000),
            "version": self.config.get("version", "3.2"),
        }
        await self._broadcast_fanout(msg)

    async def _deliver(self, endpoint, message):
        async with ClientSession() as s:
            try:
                async with s.post(endpoint, json=message, timeout=ClientTimeout(total=10)) as resp:
                    log.debug(f"Deliver to {endpoint}: {resp.status}")
            except Exception as e:
                log.error(f"Deliver failed to {endpoint}: {type(e).__name__}: {e}")

    async def _notify_loop_detected(self, sender_id: str, reason: str, content_preview: str):
        """Surface a loop detection warning to Jesse via the gateway bridge. Best-effort — never raises."""
        try:
            bridge_url = self._get_bridge_url()
            payload = {
                "agent_id": self.agent_id,
                "from": self.agent_id,
                "to": "jesse",
                "content": (
                    f"⚠️ Loop detected on {self.agent_id}: dropping message from {sender_id} "
                    f"(reason: {reason}).\nPreview: {content_preview}"
                ),
                "summary": f"Loop detected: {sender_id} → {self.agent_id} ({reason})",
                "msg_type": "loop_warning",
            }
            async with ClientSession() as s:
                async with s.post(bridge_url, json=payload, timeout=ClientTimeout(total=5)) as resp:
                    log.info(f"[LOOP] Jesse notified: {resp.status}")
        except Exception as e:
            log.warning(f"[LOOP] Failed to notify Jesse: {e}")

    # ----------------------------------------------------------
    # Standard P2P → Hermes
    # ----------------------------------------------------------

    async def _process_message(self, message):
        try:
            log.info(f"_process_message ENTERED for msg_id={message.get('id')} type={message.get('type')}")
            # Drop billing error messages — responding to these creates an infinite loop
            # (agent responds → sender resends the same error → repeat forever)
            content = message.get("content", "")
            if "402" in content or "Insufficient credits" in content or "HTTP 402" in content:
                log.warning(f"Dropping billing error message from {message.get('sender', {}).get('agentId', 'unknown')} — suppressing to avoid reply loop")
                return

            # --- Loop prevention: dedup + rate limiting ---
            sender_id = message.get("sender", {}).get("agentId", "unknown")
            now = time.time()

            # 1. Duplicate content dedup
            content_hash = hash(content)
            if sender_id in self._last_content:
                last_hash, last_ts = self._last_content[sender_id]
                if last_hash == content_hash and (now - last_ts) < self.DEDUP_WINDOW:
                    log.warning(f"[LOOP] Dropping duplicate message from {sender_id} — identical content within {self.DEDUP_WINDOW}s")
                    asyncio.create_task(self._notify_loop_detected(sender_id, "duplicate", content[:120]))
                    return
            self._last_content[sender_id] = (content_hash, now)

            # Prune dedup cache if it grows too large
            if len(self._last_content) > self.DEDUP_MAX_ENTRIES:
                oldest = sorted(self._last_content.items(), key=lambda x: x[1][1])
                self._last_content = dict(oldest[self.DEDUP_MAX_ENTRIES // 2:])

            # 2. Rate limiter
            times = self._sender_message_times[sender_id]
            times.append(now)
            while times and (now - times[0]) > self.RATE_LIMIT_WINDOW:
                times.popleft()
            if len(times) > self.RATE_LIMIT_MAX:
                log.warning(f"[LOOP] Rate limit exceeded: {sender_id} sent {len(times)} messages in {self.RATE_LIMIT_WINDOW}s (max {self.RATE_LIMIT_MAX})")
                asyncio.create_task(self._notify_loop_detected(sender_id, "rate_limit", content[:120]))
                return

            # 3. Reply-chain suppression — prevent ack-of-ack-of-ack loops
            reply_to = message.get("inReplyTo") or message.get("reply_to")
            if reply_to:
                # If we already answered this thread, suppress
                if reply_to in self._answered_ids:
                    log.info(f"[LOOP] Suppressing reply to already-answered message {reply_to} from {sender_id}")
                    return
                # If this is a reply to a reply (third+ hop), and content is SHORT and ack-like, suppress.
                # Only suppress short ack-only messages (<100 chars) — longer replies starting with
                # ack greetings are legitimate directive responses, not loop echos.
                ack_starts = ("standing by", "copy", "acknowledged", "ready", "on deck", "ack",
                             "received", "got it", "roger", "will do", "understood", "noted",
                             "loop closed", "closing the loop", "no further action",
                             "copy that", "mesh green", "mesh at full green")
                lower = content.lower().rstrip('.')
                first_words = lower[:80]
                if len(content.strip()) < 100 and any(first_words.startswith(w) for w in ack_starts):
                    log.info(f"[LOOP] Suppressing ack-of-ack from {sender_id} (reply_to={reply_to}, len={len(content)}, starts_with={content[:40].strip()})")
                    return

            # 4. Subject echo suppression — if we recently sent subject X to this agent,
            #    and they reply with subject X, it's our own message bouncing back.
            inbound_subject = message.get("subject", "")
            if inbound_subject and sender_id in self._sent_subjects:
                from collections import deque
                now_ts = time.time()
                subject_hash = hash(inbound_subject)
                recent = deque(
                    (h, t) for h, t in self._sent_subjects.get(sender_id, [])
                    if now_ts - t < self.DEDUP_WINDOW
                )
                self._sent_subjects[sender_id] = recent
                if any(h == subject_hash for h, _ in recent):
                    log.info(f"[LOOP] Suppressing subject echo from {sender_id}: \"{inbound_subject[:60]}\"")
                    asyncio.create_task(self._notify_loop_detected(sender_id, "subject_echo", inbound_subject[:120]))
                    return
            # --- End loop prevention ---

            log.debug(f"Forward to Hermes: {message.get('id')}")
            output = await self.hermes.send_and_complete(message)
            if not output:
                log.warning("No output from Hermes — not routing reply")
                return

            # Subject enforcement — every outbound Maestro reply MUST carry a Subject
            outbound_subject = extract_subject(output)
            if outbound_subject is None:
                log.warning(f"[SUBJECT] Agent {self.agent_id} failed to include Subject: line — auto-injecting")
                # Auto-generate a Subject from the first sentence (max 80 chars)
                first_line = output.split("\n")[0].strip()
                if len(first_line) > 80:
                    first_line = first_line[:77] + "..."
                if first_line:
                    outbound_subject = first_line
                else:
                    outbound_subject = f"Response from {self.agent_id}"
                # Also deliver a self-directed error so the agent learns in-context
                error_msg = {
                    "id": str(uuid.uuid4()),
                    "type": "system",
                    "content": f"❌ Subject Enforcement: Your response to {message['sender']['agentId']} was auto-corrected because it lacked a Subject: line. All Maestro messages MUST start with 'Subject: <summary>' on the first line. Your reply was still delivered, but future replies without Subject lines will also be auto-corrected.",
                    "subject": "Subject Enforcement — missing Subject line (auto-corrected)",
                    "sender": {"agentId": "system"},
                    "recipient": self.agent_id,
                    "inReplyTo": message.get("id"),
                    "timestamp": int(time.time() * 1000),
                    "version": self.config["version"],
                }
                asyncio.create_task(self.hermes.send_and_complete(error_msg))
                # DO NOT RETURN — continue routing with the auto-generated Subject

            # ACKs for directives now surface — loop guards handle noise
            if message.get("type") == "directive":
                log.info(f"Directive complete — routing ACK (loop guards active)")
            # Zero Trust outbound signing
            provenance = None
            if self._zerotrust_enabled and self._private_key and output and CRYPTO_AVAILABLE and _crypto:
                ts = int(time.time() * 1000)
                payload = _crypto.original_signature_payload(output, ts, self.agent_id)
                original_sig = _crypto.sign(payload, self._private_key)
                content_hash = _crypto.hash_string(output)
                provenance = {
                    "mode": "full",
                    "chain": [],
                    "originalSignature": original_sig,
                    "contentHash": content_hash,
                }

            # NEW: Outbound mirror — if maestro_out is ON, surface reply to gateway
            try:
                visibility_path = Path(os.environ.get("HERMES_HOME", "/home/andjesse/.hermes")) / "maestro_visibility.json"
                if visibility_path.exists():
                    vis = json.loads(visibility_path.read_text())
                    profile = self.agent_id
                    if isinstance(vis, dict) and profile in vis and vis[profile].get("out", False):
                        bridge_url = self._get_bridge_url()
                        sender_id = message.get("sender", {}).get("agentId", "unknown")
                        mirror_payload = {
                            "agent_id": profile,
                            "from": profile,
                            "to": sender_id,
                            "subject": outbound_subject,
                            "content": output,
                            "summary": f"Reply to {sender_id}: {output[:200]}",
                            "msg_type": "maestro_out",
                        }
                        asyncio.create_task(self._deliver(bridge_url, mirror_payload))
            except Exception:
                pass
            sender_id = message["sender"]["agentId"]
            sender_reg = self.registry.lookup(sender_id)
            if not sender_reg:
                log.warning(f"Sender {sender_id} not in registry")
                return
            reply = {
                "id": str(uuid.uuid4()),
                "type": "direct",
                "content": output,
                "subject": extract_subject(output),
                "sender": {"agentId": self.agent_id},
                "recipient": sender_id,
                "inReplyTo": message.get("id"),
                "timestamp": int(time.time()*1000),
                "version": self.config["version"],
            }
            if provenance:
                reply["provenance"] = provenance
            # Record sent subject for echo suppression
            sent_subject = reply.get("subject", "")
            if sent_subject:
                from collections import deque
                if sender_id not in self._sent_subjects:
                    self._sent_subjects[sender_id] = deque()
                self._sent_subjects[sender_id].append((hash(sent_subject), time.time()))
                # Prune old entries
                if hasattr(self._sent_subjects[sender_id], '__len__') and len(self._sent_subjects[sender_id]) > 50:
                    while len(self._sent_subjects[sender_id]) > 50:
                        self._sent_subjects[sender_id].popleft()
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

    # ------------------------------------------------------------------
    # Notifications toggle (runtime on/off)
    # ------------------------------------------------------------------

    async def handle_notifications_toggle(self, req):
        """POST /maestro/notifications/toggle — body: {"enabled": true|false} or {} to read current state."""
        try:
            data = await req.json()
        except Exception:
            data = {}
        enabled = data.get("enabled")
        flag_path = Path(f"/home/andjesse/.maestro/blackboards/surface_enabled_{self.agent_id}.json")
        if enabled is None:
            # Return current state
            current = {"enabled": True}
            if flag_path.exists():
                try:
                    current = json.loads(flag_path.read_text())
                except Exception:
                    pass
            return web.json_response({"ok": True, "agent_id": self.agent_id, "notifications_enabled": current.get("enabled", True)})
        try:
            flag_path.write_text(json.dumps({"enabled": bool(enabled), "updated_at": int(time.time() * 1000)}, indent=2))
            return web.json_response({"ok": True, "agent_id": self.agent_id, "notifications_enabled": enabled})
        except Exception as e:
            log.error(f"Failed to write surface_enabled: {e}")
            return web.json_response({"ok": False, "reason": str(e)}, status=500)

    # ------------------------------------------------------------------
    # Work log blackboard
    # ------------------------------------------------------------------

    def _write_work_log(self, message: dict):
        """Append inbound Maestro message to a structured work log."""
        log_path = Path(f"/home/andjesse/.maestro/blackboards/work_log_{self.agent_id}.json")
        raw_content = message.get("content", "")
        if isinstance(raw_content, dict):
            raw_content = raw_content.get("text", "")
        if not isinstance(raw_content, str):
            raw_content = str(raw_content)
        entry = {
            "id": message.get("id"),
            "sender": message.get("sender", {}).get("agentId", "unknown"),
            "type": message.get("type", "direct"),
            "content": raw_content[:2000],
            "timestamp": int(time.time() * 1000),
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
        }
        try:
            logs = []
            if log_path.exists():
                try:
                    logs = json.loads(log_path.read_text())
                    if not isinstance(logs, list):
                        logs = []
                except Exception:
                    logs = []
            logs.append(entry)
            # Keep last 50 entries per agent (hygiene target is 50)
            logs = logs[-50:]
            # Time-based pruning: remove entries older than 24 hours
            MAX_AGE_HOURS = 24
            cutoff_ms = int((time.time() - MAX_AGE_HOURS * 3600) * 1000)
            logs = [e for e in logs if e.get("timestamp", 0) > cutoff_ms]
            log_path.write_text(json.dumps(logs, indent=2, ensure_ascii=False))
        except Exception as e:
            log.warning(f"Work log write failed: {type(e).__name__}: {e}")

    def _read_work_log(self, agent_id: str = None, limit: int = 20):
        """Read work log entries. Defaults to this agent unless agent_id provided."""
        target = agent_id or self.agent_id
        log_path = Path(f"/home/andjesse/.maestro/blackboards/work_log_{target}.json")
        if not log_path.exists():
            return []
        try:
            logs = json.loads(log_path.read_text())
            if not isinstance(logs, list):
                return []
            return logs[-limit:]
        except Exception:
            return []

    async def handle_worklog_query(self, req):
        """POST /maestro/worklog/query — body: {\"agent_id\": \"proteus\", \"limit\": 10}"""
        try:
            data = await req.json()
        except Exception:
            data = {}
        agent_id = data.get("agent_id") or self.agent_id
        limit = min(int(data.get("limit", 20)), 100)
        entries = self._read_work_log(agent_id=agent_id, limit=limit)
        return web.json_response({"ok": True, "agent_id": agent_id, "count": len(entries), "entries": entries})

    async def _handle_worklog_query_msg(self, message: dict):
        """Handle worklog:query Maestro message type.

        Body: {agent_id?: str, limit?: int}
        Returns: {ok, agent_id, count, entries}
        """
        agent_id = message.get("agent_id") or self.agent_id
        limit = min(int(message.get("limit", 20)), 100)
        entries = self._read_work_log(agent_id=agent_id, limit=limit)
        return web.json_response({"ok": True, "agent_id": agent_id, "count": len(entries), "entries": entries})

    # ------------------------------------------------------------------
    # Task tracking (start/finish timestamps for /work /workall display)
    # ------------------------------------------------------------------

    async def handle_task_start(self, req):
        """POST /maestro/task/start — body: {agent_id, description, timestamp}.
        Appends a START record to the agent's task log.
        """
        try: data = await req.json()
        except Exception: data = {}
        agent_id = data.get("agent_id") or self.agent_id
        desc = data.get("description", data.get("content", "Task started")).strip()
        ts = int(data.get("timestamp", time.time() * 1000))
        if not desc:
            return web.json_response({"ok": False, "error": "missing description"}, status=400)
        entry = {
            "type": "start",
            "agent_id": agent_id,
            "description": desc,
            "started_at": ts,
            "started_at_iso": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat(),
            "finished_at": None,
            "duration_sec": None,
        }
        self._append_task_log(agent_id, entry)
        return web.json_response({"ok": True, "agent_id": agent_id, "task": entry})

    async def handle_task_finish(self, req):
        """POST /maestro/task/finish — body: {agent_id, description, timestamp}.
        Marks the most recent matching START record as finished.
        """
        try: data = await req.json()
        except Exception: data = {}
        agent_id = data.get("agent_id") or self.agent_id
        desc = data.get("description", "").strip()
        ts = int(data.get("timestamp", time.time() * 1000))
        updated = self._finish_task_log(agent_id, desc, ts)
        return web.json_response({"ok": updated is not None, "agent_id": agent_id, "updated": updated})

    def _task_log_path(self, agent_id: str) -> Path:
        return self.bb_root / f"task_log_{agent_id}.json"

    def _append_task_log(self, agent_id: str, entry: dict):
        p = self._task_log_path(agent_id)
        logs = []
        if p.exists():
            try:
                logs = json.loads(p.read_text())
                if not isinstance(logs, list): logs = []
            except Exception: logs = []
        logs.append(entry)
        logs = logs[-200:]  # cap
        try:
            p.write_text(json.dumps(logs, indent=2, ensure_ascii=False))
        except Exception as e:
            log.warning(f"Task log write failed: {e}")

    def _finish_task_log(self, agent_id: str, description: str, ts: int) -> dict | None:
        p = self._task_log_path(agent_id)
        if not p.exists(): return None
        try:
            logs = json.loads(p.read_text())
            if not isinstance(logs, list): return None
            entry = None
            if description:
                entry = next((e for e in reversed(logs) if e.get("type") == "start" and e.get("description") == description), None)
            if not entry:
                entry = next((e for e in reversed(logs) if e.get("type") == "start" and e.get("finished_at") is None), None)
            if not entry: return None
            entry["finished_at"] = ts
            entry["finished_at_iso"] = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
            start_ts = entry.get("started_at", ts)
            entry["duration_sec"] = round((ts - start_ts) / 1000, 1)
            p.write_text(json.dumps(logs, indent=2, ensure_ascii=False))
            return entry
        except Exception as e:
            log.warning(f"Task log finish failed: {e}")
            return None

    def _read_task_log(self, agent_id: str = None, limit: int = 20) -> list:
        target = agent_id or self.agent_id
        p = self._task_log_path(target)
        if not p.exists(): return []
        try:
            logs = json.loads(p.read_text())
            if not isinstance(logs, list): return []
            return logs[-limit:]
        except Exception: return []

    # ------------------------------------------------------------------
    # Gateway surface
    # ------------------------------------------------------------------

    async def _surface_to_gateway(self, message: dict):
        """Post a lightweight notification to the gateway bridge for Telegram visibility."""
        # Runtime toggle: check per-agent file-based flag so Jesse can turn notifications off per agent
        enable_path = Path(f"/home/andjesse/.maestro/blackboards/surface_enabled_{self.agent_id}.json")
        if enable_path.exists():
            try:
                data = json.loads(enable_path.read_text())
                if isinstance(data, dict) and data.get("enabled", True) is False:
                    return
            except Exception:
                pass
        # Fallback to legacy global flag for backward compat
        legacy_path = Path("/home/andjesse/.maestro/surface_enabled")
        if legacy_path.exists():
            try:
                if legacy_path.read_text().strip().lower() == "false":
                    return
            except Exception:
                pass
        # NEW: Check maestro_in toggle from gateway state
        try:
            visibility_path = Path(os.environ.get("HERMES_HOME", "/home/andjesse/.hermes")) / "maestro_visibility.json"
            if visibility_path.exists():
                vis = json.loads(visibility_path.read_text())
                profile = self.agent_id
                if isinstance(vis, dict) and profile in vis:
                    if vis[profile].get("in", True) is False:
                        log.debug(f"Gateway surface suppressed — maestro_in is OFF for {profile}")
                        return
        except Exception:
            pass
        bridge_url = self._get_bridge_url()
        sender = message.get("sender", {}).get("agentId", "unknown")
        try:
            content = message.get("content", "")
            # Telegram message limit is 4096 chars. Use full content up to that,
            # truncate with ellipsis if over, and attach a file hint for overflow.
            if len(content) > 3900:
                content = content[:3897] + "..."
            payload = {
                "agent_id": self.agent_id,
                "from": sender,
                "to": message.get("recipient", ""),
                "subject": message.get("subject") or extract_subject(content) or fallback_subject(content),
                "content": content,
                "summary": content[:200],
                "msg_type": "maestro_out" if sender == self.agent_id else message.get("type", "direct"),
            }
            async with ClientSession() as s:
                async with s.post(bridge_url, json=payload, timeout=ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        log.info(f"Surfaced to gateway: from {sender}")
                    else:
                        log.warning(f"Gateway surface failed: {resp.status}")
        except Exception as e:
            log.debug(f"Gateway surface skipped ({type(e).__name__}): {e}")


    # ------------------------------------------------------------------
    # Memory handlers (Maestro messages + REST)
    # ------------------------------------------------------------------

    async def _process_memory_write(self, message):
        content = message.get("content", {})
        if isinstance(content, str):
            try: content = json.loads(content)
            except Exception: content = {}
        agent_id = content.get("agent_id", message.get("sender", {}).get("agentId"))
        requester = message.get("sender", {}).get("agentId", "")
        if not agent_id:
            await self._route_system_reply(message, json.dumps({"ok": False, "reason": "missing agent_id"}))
            return
        mem_id = content.get("memory_id") or str(uuid.uuid4())
        result = self.memory_service.write(
            agent_id, content=content.get("content"), memory_id=mem_id,
            tags=content.get("tags"), importance=content.get("importance", 0.5),
            shared_with=content.get("shared_with", ["*"]),
            ttl_seconds=content.get("ttl_seconds"),
            price=content.get("price", 0.0)
        )
        self.logger.log(self.agent_id, "memory_write", {"agent_id": agent_id, "memory_id": mem_id}, result=result)
        await self._route_system_reply(message, json.dumps(result))

    async def _process_memory_read(self, message):
        content = message.get("content", {})
        if isinstance(content, str):
            try: content = json.loads(content)
            except Exception: content = {}
        agent_id = content.get("agent_id")
        mem_id = content.get("memory_id")
        requester = content.get("requester", message.get("sender", {}).get("agentId", ""))
        if not agent_id or not mem_id:
            await self._route_system_reply(message, json.dumps({"ok": False, "reason": "missing agent_id or memory_id"}))
            return
        result = self.memory_service.read(agent_id, mem_id, requester)
        self.logger.log(self.agent_id, "memory_read", {"agent_id": agent_id, "memory_id": mem_id, "requester": requester}, result=result)
        await self._route_system_reply(message, json.dumps(result))

    async def _process_memory_search(self, message):
        content = message.get("content", {})
        if isinstance(content, str):
            try: content = json.loads(content)
            except Exception: content = {}
        agent_id = content.get("agent_id")
        requester = content.get("requester", message.get("sender", {}).get("agentId", ""))
        if not agent_id:
            await self._route_system_reply(message, json.dumps({"ok": False, "reason": "missing agent_id"}))
            return
        result = self.memory_service.search(
            agent_id, requester,
            query=content.get("query"),
            tags=content.get("tags"),
            min_importance=content.get("min_importance"),
            limit=content.get("limit", 10)
        )
        self.logger.log(self.agent_id, "memory_search", {"agent_id": agent_id, "requester": requester, "query": content.get("query")}, result=result)
        await self._route_system_reply(message, json.dumps(result))

    async def _process_memory_delete(self, message):
        content = message.get("content", {})
        if isinstance(content, str):
            try: content = json.loads(content)
            except Exception: content = {}
        agent_id = content.get("agent_id")
        mem_id = content.get("memory_id")
        requester = content.get("requester", message.get("sender", {}).get("agentId", ""))
        if not agent_id or not mem_id:
            await self._route_system_reply(message, json.dumps({"ok": False, "reason": "missing agent_id or memory_id"}))
            return
        result = self.memory_service.delete(agent_id, mem_id, requester)
        self.logger.log(self.agent_id, "memory_delete", {"agent_id": agent_id, "memory_id": mem_id, "requester": requester}, result=result)
        await self._route_system_reply(message, json.dumps(result))

    async def _process_memory_list(self, message):
        content = message.get("content", {})
        if isinstance(content, str):
            try: content = json.loads(content)
            except Exception: content = {}
        agent_id = content.get("agent_id")
        requester = content.get("requester", message.get("sender", {}).get("agentId", ""))
        if not agent_id:
            await self._route_system_reply(message, json.dumps({"ok": False, "reason": "missing agent_id"}))
            return
        result = self.memory_service.list(agent_id, requester, limit=content.get("limit", 50))
        self.logger.log(self.agent_id, "memory_list", {"agent_id": agent_id, "requester": requester, "limit": content.get("limit", 50)}, result=result)
        await self._route_system_reply(message, json.dumps(result))

    # REST wrappers -----------------------------------------------------

    async def handle_memory_write(self, req):
        try: data = await req.json()
        except Exception: return web.json_response({"ok": False, "reason": "invalid_json"}, status=400)
        agent_id = data.get("agent_id")
        payload = data.get("content")
        if not agent_id or payload is None:
            return web.json_response({"ok": False, "reason": "missing agent_id or content"}, status=400)
        mem_id = data.get("memory_id") or str(uuid.uuid4())
        result = self.memory_service.write(
            agent_id, content=payload, memory_id=mem_id,
            tags=data.get("tags"), importance=data.get("importance", 0.5),
            shared_with=data.get("shared_with", ["*"]),
            ttl_seconds=data.get("ttl_seconds"),
            price=data.get("price", 0.0)
        )
        return web.json_response(result)

    async def handle_memory_read(self, req):
        try: data = await req.json()
        except Exception: return web.json_response({"ok": False, "reason": "invalid_json"}, status=400)
        agent_id = data.get("agent_id")
        mem_id = data.get("memory_id")
        requester = data.get("requester", "")
        if not agent_id or not mem_id:
            return web.json_response({"ok": False, "reason": "missing agent_id or memory_id"}, status=400)
        result = self.memory_service.read(agent_id, mem_id, requester)
        if not result.get("ok"):
            status = 403 if result.get("reason") in ("access_denied", "unauthorized_requester") else 404
            return web.json_response(result, status=status)
        return web.json_response(result)

    async def handle_memory_search(self, req):
        try: data = await req.json()
        except Exception: return web.json_response({"ok": False, "reason": "invalid_json"}, status=400)
        agent_id = data.get("agent_id")
        requester = data.get("requester", "")
        if not agent_id:
            return web.json_response({"ok": False, "reason": "missing agent_id"}, status=400)
        result = self.memory_service.search(
            agent_id, requester,
            query=data.get("query"),
            tags=data.get("tags"),
            min_importance=data.get("min_importance"),
            limit=data.get("limit", 10)
        )
        status = 200 if result.get("ok") else 403
        return web.json_response(result, status=status)

    async def handle_memory_delete(self, req):
        try: data = await req.json()
        except Exception: return web.json_response({"ok": False, "reason": "invalid_json"}, status=400)
        agent_id = data.get("agent_id")
        mem_id = data.get("memory_id")
        requester = data.get("requester", "")
        if not agent_id or not mem_id:
            return web.json_response({"ok": False, "reason": "missing agent_id or memory_id"}, status=400)
        result = self.memory_service.delete(agent_id, mem_id, requester)
        if not result.get("ok"):
            status = 403 if result.get("reason") in ("forbidden", "unauthorized_requester") else 404
            return web.json_response(result, status=status)
        return web.json_response(result)

    async def handle_memory_list(self, req):
        try: data = await req.json()
        except Exception: return web.json_response({"ok": False, "reason": "invalid_json"}, status=400)
        agent_id = data.get("agent_id")
        requester = data.get("requester", "")
        if not agent_id:
            return web.json_response({"ok": False, "reason": "missing agent_id"}, status=400)
        result = self.memory_service.list(agent_id, requester, limit=data.get("limit", 50))
        status = 200 if result.get("ok") else 403
        return web.json_response(result, status=status)

    async def handle_bb_search(self, req):
        try: data = await req.json()
        except Exception: return web.json_response({"ok": False, "reason": "invalid_json"}, status=400)
        board_id = data.get("boardId", "default")
        prefix = data.get("prefix")
        query = data.get("query")
        limit = min(int(data.get("limit", 20)), 100)
        bb_path = self._get_bb_path(board_id)
        if not bb_path.exists():
            return web.json_response({"ok": True, "results": [], "total": 0})
        try:
            raw = json.loads(bb_path.read_text())
            results = []
            for k, v in raw.items():
                if prefix and not k.startswith(prefix):
                    continue
                if query and isinstance(v, dict):
                    val_str = json.dumps(v)
                    if query.lower() not in val_str.lower() and query.lower() not in k.lower():
                        continue
                results.append({"key": k, "value": v})
            total = len(results)
            results = results[:limit]
            return web.json_response({"ok": True, "results": results, "total": total})
        except Exception as e:
            return web.json_response({"ok": False, "reason": str(e)}, status=500)

    async def handle_bb_delete(self, req):
        try: data = await req.json()
        except Exception: return web.json_response({"ok": False, "reason": "invalid_json"}, status=400)
        board_id = data.get("boardId", "default")
        key = data.get("key")
        prefix = data.get("prefix")
        bb_path = self._get_bb_path(board_id)
        if not bb_path.exists():
            return web.json_response({"ok": False, "reason": "not_found"}, status=404)
        try:
            raw = json.loads(bb_path.read_text())
            deleted = 0
            if key:
                if key in raw:
                    del raw[key]
                    deleted = 1
            elif prefix:
                keys = [k for k in raw if k.startswith(prefix)]
                for k in keys:
                    del raw[k]
                deleted = len(keys)
            bb_path.write_text(json.dumps(raw, indent=2))
            return web.json_response({"ok": True, "deleted": deleted})
        except Exception as e:
            return web.json_response({"ok": False, "reason": str(e)}, status=500)

    async def handle_bb_get(self, req):
        board = req.match_info["board"]
        bb_path = self._get_bb_path(board)
        if not bb_path.exists():
            return web.json_response({"ok": False, "reason": "not_found"}, status=404)
        try:
            data = json.loads(bb_path.read_text())
            return web.json_response(data)
        except Exception as e:
            return web.json_response({"ok": False, "reason": str(e)}, status=500)

    async def handle_bb_post(self, req):
        board = req.match_info["board"]
        try:
            data = await req.json()
        except Exception:
            return web.json_response({"ok": False, "reason": "invalid_json"}, status=400)
        bb_path = self._get_bb_path(board)
        try:
            bb_path.write_text(json.dumps(data, indent=2))
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "reason": str(e)}, status=500)

    async def handle_bb_search_get(self, req):
        board = req.match_info["board"]
        query = req.query.get("q", "")
        bb_path = self._get_bb_path(board)
        if not bb_path.exists():
            return web.json_response({"ok": True, "results": [], "total": 0})
        try:
            raw = json.loads(bb_path.read_text())
        except Exception as e:
            return web.json_response({"ok": False, "reason": str(e)}, status=500)
        if not query:
            results = [{"key": k, "value": v} for k, v in raw.items()]
            return web.json_response({"ok": True, "results": results, "total": len(results)})
        q = query.lower()
        results = []
        for k, v in raw.items():
            if isinstance(v, str):
                if q in v.lower() or q in k.lower():
                    results.append({"key": k, "value": v})
            elif isinstance(v, dict):
                val_str = json.dumps(v)
                if q in val_str.lower() or q in k.lower():
                    results.append({"key": k, "value": v})
            else:
                val_str = str(v)
                if q in val_str.lower() or q in k.lower():
                    results.append({"key": k, "value": v})
        return web.json_response({"ok": True, "results": results, "total": len(results)})

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
        self.registry.register(self.agent_id, f"http://127.0.0.1:{self.port}/message", public_key=self._public_key)
        self.started_at = int(time.time()*1000)
        runner = web.AppRunner(self.app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", self.port).start()
        log.info(f"{self.agent_id} listening on 0.0.0.0:{self.port}")
        log.info(f"BB REST surface registered on port {self.port}")
        log.info("Ready.")
        log.info("Features: dedup, BB_WRITE, BB_READ, BB_SEARCH, BB_DELETE, BB_RECALL, broadcast, /message, /maestro/webhook, /health, /connections, calendar-triggers")
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
