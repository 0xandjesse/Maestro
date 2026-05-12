"""Core transport broker with persistent queue and retry logic."""
import asyncio
import json
import time
import logging
import uuid
from dataclasses import dataclass
from typing import Optional, Callable, Dict
from pathlib import Path

from ..storage.queue import MessageQueue, QueuedMessage
from ..storage.registry import AgentRegistry, ContactCard

log = logging.getLogger("maestro.transport")

@dataclass
class TransportConfig:
    agent_id: str
    listen_port: int
    hermes_api_url: Optional[str]
    hermes_api_key: Optional[str]
    db_path: str
    registry_db_path: str
    blackboard_db_path: str
    max_retries: int = 3
    base_retry_delay: float = 2.0
    max_retry_delay: float = 60.0

class ConnectionBroker:
    """Manages persistent outbound queue, retries, and agent discovery."""

    def __init__(self, config: TransportConfig):
        self.config = config
        self.queue = MessageQueue(config.db_path)
        self.registry = AgentRegistry(config.registry_db_path)
        self._running = False
        self._retry_task: Optional[asyncio.Task] = None
        self._handlers: Dict[str, Callable] = {}

    def on_message(self, msg_type: str, handler: Callable):
        self._handlers[msg_type] = handler

    @property
    def agent_id(self) -> str:
        return self.config.agent_id

    async def start(self):
        self._running = True
        self._retry_task = asyncio.create_task(self._retry_loop())
        log.info(f"Broker started for {self.config.agent_id}")

    async def stop(self):
        self._running = False
        if self._retry_task:
            self._retry_task.cancel()
            try:
                await self._retry_task
            except asyncio.CancelledError:
                pass
        log.info(f"Broker stopped for {self.config.agent_id}")

    def send_message(self, recipient: str, message) -> str:
        """Enqueue a MaestroMessage for delivery."""
        from ..protocol.messages import MaestroMessage
        if isinstance(message, MaestroMessage):
            msg_id = message.id or str(uuid.uuid4())
            headers = message.headers
            content = message.content
            msg_type = message.type
        else:
            raise TypeError("message must be a MaestroMessage")
        return self.send(recipient, msg_type, content, msg_id=msg_id, headers=headers)

    async def broadcast(self, message):
        """Send message to all registered agents (enqueue, non-blocking)."""
        contacts = self.registry.list_contacts()
        count = 0
        for contact in contacts:
            if contact.agent_id == self.config.agent_id:
                continue
            self.send_message(contact.agent_id, message)
            count += 1
        if count:
            log.info(f"Broadcast queued to {count} peers")

    def send(self, recipient: str, msg_type: str, content: str, msg_id: Optional[str] = None, headers: Optional[Dict] = None) -> str:
        """Enqueue a message for delivery. Returns message ID."""

        msg_id = msg_id or str(uuid.uuid4())
        now = time.time()
        msg = QueuedMessage(
            id=msg_id,
            sender_agent_id=self.config.agent_id,
            recipient_agent_id=recipient,
            msg_type=msg_type,
            content=content,
            headers=json.dumps(headers or {}),
            status="pending",
            attempts=0,
            created_at=now,
            updated_at=now,
            next_attempt_at=now,
            last_error=None,
        )
        self.queue.enqueue(msg)
        log.info(f"Enqueued {msg_id} -> {recipient} ({msg_type})")
        return msg_id

    async def _retry_loop(self):
        while self._running:
            pending = self.queue.get_pending(limit=50)
            for msg in pending:
                await self._attempt_delivery(msg)
            await asyncio.sleep(1)

    async def _attempt_delivery(self, msg: QueuedMessage):
        contact = self.registry.get_contact(msg.recipient_agent_id)
        if not contact:
            err = f"No contact for {msg.recipient_agent_id}"
            log.warning(err)
            self.queue.mark_failed(msg.id, err)
            return

        endpoints = json.loads(contact.endpoints)
        if not endpoints:
            err = f"No endpoints for {msg.recipient_agent_id}"
            log.warning(err)
            self.queue.mark_failed(msg.id, err)
            return

        import aiohttp
        payload = {
            "id": msg.id,
            "type": msg.msg_type,
            "sender": {"agentId": msg.sender_agent_id},
            "content": msg.content,
        }
        headers = json.loads(msg.headers) if msg.headers else {}
        if headers:
            payload["headers"] = headers

        for ep in endpoints:
            url = ep.get("url")
            if not url:
                continue
            try:
                timeout = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, json=payload) as resp:
                        if resp.status == 200:
                            body = await resp.json()
                            if body.get("accepted"):
                                self.queue.mark_delivered(msg.id)
                                log.info(f"Delivered {msg.id} to {url}")
                                return
            except Exception as e:
                log.warning(f"Delivery failed {msg.id} to {url}: {e}")
                continue

        # All endpoints failed — schedule retry
        attempts = msg.attempts + 1
        if attempts > self.config.max_retries:
            self.queue.mark_failed(msg.id, "Max retries exceeded")
            log.error(f"Message {msg.id} failed permanently")
        else:
            delay = min(self.config.base_retry_delay * (2 ** (attempts - 1)), self.config.max_retry_delay)
            next_attempt = time.time() + delay
            self.queue.mark_retry(msg.id, next_attempt)
            log.info(f"Scheduled retry {msg.id} in {delay:.1f}s (failure {attempts}/{self.config.max_retries})")

    def handle_inbound(self, message: dict) -> dict:
        """Process an inbound message. Returns ack/nack response."""
        msg_id = message.get("id")
        msg_type = message.get("type")
        sender = message.get("sender", {}).get("agentId", "?")

        if not msg_id or not msg_type:
            return {"accepted": False, "reason": "Missing id or type"}

        log.info(f"Inbound from {sender} type={msg_type} id={msg_id}")

        handler = self._handlers.get(msg_type)
        if handler:
            try:
                import inspect
                if inspect.iscoroutinefunction(handler):
                    asyncio.create_task(handler(message))
                else:
                    handler(message)
            except Exception as e:
                log.error(f"Handler error for {msg_type}: {e}")
                return {"accepted": False, "reason": str(e)}

        return {"accepted": True, "ack": msg_id}
