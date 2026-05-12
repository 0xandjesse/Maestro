"""Google Calendar trigger plugin for Maestro SDK.

Polls a shared calendar for trigger events and routes them as Maestro messages
to recipients tagged with [TO:recipient] in the event description.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from maestro_sdk.plugins.manager import Plugin, register_builtin
from maestro_sdk.protocol.messages import MaestroMessage

log = logging.getLogger("maestro.plugins.calendar")

# Soft import Google Calendar libs

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    CALENDAR_AVAILABLE = True
except ImportError:
    CALENDAR_AVAILABLE = False


@register_builtin
class CalendarTriggerPlugin(Plugin):
    """Plugin that watches a Google Calendar and fires Maestro triggers."""

    name = "calendar"
    version = "0.1"

    TO_TAG_RE = re.compile(r'^\[TO:\s*([^\]]+)\]\s*(.*)$', re.IGNORECASE | re.DOTALL)

    def __init__(self):
        self._broker = None
        self._config: Dict[str, Any] = {}
        self._credentials = None
        self._service = None
        self._poll_interval = 60
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._seen: set = set()  # runtime dedup per poll window
        self._credentials_path = Path("~/.maestro/gcal-credentials.json").expanduser()
        self._calendar_id = ""

    async def setup(self, broker, config: Dict[str, Any]) -> bool:
        self._broker = broker
        self._config = config
        self._credentials_path = Path(config.get("credentialsPath", str(self._credentials_path)))
        self._calendar_id = config.get("calendarId", "")
        self._poll_interval = config.get("pollInterval", 60)

        if not CALENDAR_AVAILABLE:
            log.warning("Plugin 'calendar' disabled: google-auth/google-api-python-client not installed")
            return False
        if not self._calendar_id:
            log.warning("Plugin 'calendar' disabled: no calendarId in config")
            return False
        if not self._credentials_path.exists():
            log.warning(f"Plugin 'calendar' disabled: credentials not found at {self._credentials_path}")
            return False

        if not self._build_service():
            log.error("Plugin 'calendar': failed to build Google service")
            return False

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        log.info(f"Plugin 'calendar' started: polling {self._calendar_id} every {self._poll_interval}s")
        return True

    async def teardown(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("Plugin 'calendar' stopped")

    def _build_service(self) -> bool:
        try:
            data = json.loads(self._credentials_path.read_text())
            self._credentials = Credentials(
                token=None,
                refresh_token=data.get("refresh_token"),
                token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=data.get("client_id"),
                client_secret=data.get("client_secret"),
                scopes=[data.get("scope", "https://www.googleapis.com/auth/calendar")]
            )
            self._service = build("calendar", "v3", credentials=self._credentials, cache_discovery=False)
            return True
        except Exception as e:
            log.error(f"CalendarPlugin: failed to build service: {e}")
            return False

    def _parse_event(self, event: dict) -> Optional[Tuple[str, str, str]]:
        summary = event.get("summary", "")
        description = event.get("description", "") or summary
        event_id = event.get("id", "")
        match = self.TO_TAG_RE.match(description.strip())
        if match:
            return match.group(1).strip(), match.group(2).strip(), event_id
        match = self.TO_TAG_RE.match(summary.strip())
        if match:
            return match.group(1).strip(), match.group(2).strip() or description.strip(), event_id
        return None

    async def _poll_loop(self):
        while self._running:
            try:
                await self._poll_once()
            except Exception as e:
                log.error(f"CalendarPlugin: poll error: {e}")
            await asyncio.sleep(self._poll_interval)

    async def _poll_once(self):
        if not self._service:
            if not self._build_service():
                return

        now = datetime.now(timezone.utc)
        time_min = (now - timedelta(minutes=1)).isoformat()
        time_max = (now + timedelta(minutes=1)).isoformat()

        try:
            result = self._service.events().list(
                calendarId=self._calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=10,
            ).execute()
            events = result.get("items", [])
            for event in events:
                event_id = event.get("id", "")
                if event_id in self._seen:
                    continue
                parsed = self._parse_event(event)
                if not parsed:
                    continue
                recipient, content, evt_id = parsed
                self._seen.add(event_id)
                await self._fire_trigger(recipient, content, evt_id, event.get("summary", ""))
                # Prune seen set if too large
                if len(self._seen) > 5000:
                    self._seen = set(list(self._seen)[-2500:])
        except Exception as e:
            log.error(f"CalendarPlugin: polling error: {e}")

    async def _fire_trigger(self, recipient: str, content: str, event_id: str, event_title: str):
        msg = MaestroMessage(
            id=f"gcal-trigger-{event_id}-{int(datetime.now().timestamp())}",
            type="direct",
            sender={"agentId": self._broker.agent_id},
            recipient=recipient,
            content=content,
            headers={
                "source": "calendar-trigger",
                "event_id": event_id,
                "event_title": event_title,
                "calendar_id": self._calendar_id,
            },
        )
        if recipient in ("broadcast", "*"):
            log.info(f"Calendar trigger: broadcast '{event_title}'")
            await self._broker.broadcast(msg)
        else:
            log.info(f"Calendar trigger: fire to {recipient} for '{event_title}'")
            self._broker.send_message(recipient, msg)  # sync enqueue — no await
