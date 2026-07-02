"""Message Router — in-memory implementation.

Implements the MessageRouter interface with:
* SeenSet deduplication
* Message validation
* Intent-aware routing (via IntentClassifier from M6)
* Rate limiting per sender
* Broadcast fanout
"""

from __future__ import annotations

import time
from collections import defaultdict

from nucleus.modules.intent_classifier import DefaultIntentClassifier, Intent

from .dedup import SeenSet
from .interface import DeliveryResult, MessageEnvelope, MessageRouter, RouteResult
from .schema import validate_message


# ── rate limiting defaults ─────────────────────────────────────────────

_DEFAULT_RATE_LIMIT = 60       # max messages per window
_DEFAULT_RATE_WINDOW_MS = 60_000  # 1 minute


class InMemoryMessageRouter(MessageRouter):
    """In-memory message router with dedup, validation, rate limiting, and broadcast.

    Parameters
    ----------
    peers : dict[str, dict] | None
        Known peers for broadcast fanout.  Keys are agent IDs, values are
        endpoint dicts (e.g. {agentId, endpoint}).
    rate_limit : int
        Maximum messages per sender per rate window.
    rate_window_ms : int
        Rate-limiting window in milliseconds.
    seen_max_size : int
        Maximum entries in the SeenSet dedup store.
    seen_ttl_ms : int | None
        TTL for SeenSet entries in milliseconds.
    """

    def __init__(
        self,
        peers: dict[str, dict] | None = None,
        rate_limit: int = _DEFAULT_RATE_LIMIT,
        rate_window_ms: int = _DEFAULT_RATE_WINDOW_MS,
        seen_max_size: int = 10_000,
        seen_ttl_ms: int | None = 300_000,
    ) -> None:
        self._peers: dict[str, dict] = dict(peers) if peers else {}
        self._rate_limit = rate_limit
        self._rate_window_ms = rate_window_ms
        self._seen = SeenSet(max_size=seen_max_size, ttl_ms=seen_ttl_ms)
        self._classifier = DefaultIntentClassifier()

        # Rate tracking: sender_agent_id -> list of timestamps (ms)
        self._rate_buckets: dict[str, list[int]] = defaultdict(list)

    # ── public API ─────────────────────────────────────────────────────

    def route(self, message: MessageEnvelope) -> RouteResult:
        """Route a message envelope to its destination.

        Steps:
        1. Validate the message
        2. Check dedup (SeenSet)
        3. Check rate limit
        4. Classify intent (if not already set)
        5. Route based on intent and recipient
        """
        # 1. Validation
        errors = validate_message(message)
        if errors:
            return RouteResult(
                result=DeliveryResult.REJECTED,
                message_id=message.id,
                detail=f"Validation failed: {'; '.join(errors)}",
            )

        # 2. Dedup
        if self._seen.is_duplicate(message.id):
            return RouteResult(
                result=DeliveryResult.DUPLICATE,
                message_id=message.id,
                detail="Duplicate message ID",
            )

        # 3. Rate limiting
        sender_id = message.sender.get("agentId", "unknown")
        if not self._check_rate(sender_id):
            return RouteResult(
                result=DeliveryResult.REJECTED,
                message_id=message.id,
                detail=f"Rate limit exceeded for sender {sender_id!r}",
            )

        # 4. Intent classification (if not already set)
        intent_str = message.intent
        if intent_str is None:
            result = self._classifier.classify(message.content, message.type)
            intent_str = result.intent.value

        # 5. Intent-aware routing
        return self._route_by_intent(message, intent_str)

    def validate(self, message: MessageEnvelope) -> bool:
        """Validate a message envelope's required fields.

        Returns True if the message passes all validation checks.
        """
        errors = validate_message(message)
        return len(errors) == 0

    def get_seen_count(self) -> int:
        """Return the number of unique message IDs tracked in the dedup store."""
        return self._seen.count()

    # ── peer management ─────────────────────────────────────────────────

    def register_peer(self, agent_id: str, endpoint: dict | None = None) -> None:
        """Register a peer for broadcast fanout.

        Parameters
        ----------
        agent_id : str
            The agent ID to register.
        endpoint : dict | None
            Optional endpoint info (e.g. {agentId, endpoint}).
        """
        self._peers[agent_id] = endpoint or {"agentId": agent_id}

    def remove_peer(self, agent_id: str) -> bool:
        """Remove a peer. Returns True if the peer was found and removed."""
        if agent_id in self._peers:
            del self._peers[agent_id]
            return True
        return False

    def get_peers(self) -> dict[str, dict]:
        """Return a copy of the current peer registry."""
        return dict(self._peers)

    # ── internal routing ────────────────────────────────────────────────

    def _route_by_intent(self, message: MessageEnvelope, intent_str: str) -> RouteResult:
        """Route based on intent classification.

        - ack → accept, no reply
        - work → route to agent for processing
        - query → route, expect reply
        - status → log, no reply
        - system → process structurally, no LLM
        - unknown → route as direct
        """
        recipient_id = message.recipient.get("agentId", "")

        # Broadcast fanout
        if recipient_id in ("broadcast", "*"):
            return self._broadcast(message, intent_str)

        # Intent-specific handling
        if intent_str == Intent.ACK.value:
            # ACK: accept, no further processing needed
            return RouteResult(
                result=DeliveryResult.DELIVERED,
                message_id=message.id,
                detail="ACK accepted — no reply required",
                delivered_to=recipient_id,
            )

        elif intent_str == Intent.STATUS.value:
            # STATUS: log, no reply
            return RouteResult(
                result=DeliveryResult.DELIVERED,
                message_id=message.id,
                detail="Status logged — no reply required",
                delivered_to=recipient_id,
            )

        elif intent_str == Intent.SYSTEM.value:
            # SYSTEM: process structurally, no LLM
            return RouteResult(
                result=DeliveryResult.DELIVERED,
                message_id=message.id,
                detail="System message processed structurally",
                delivered_to=recipient_id,
            )

        elif intent_str in (Intent.WORK.value, Intent.QUERY.value):
            # WORK / QUERY: route to agent for processing
            if recipient_id in self._peers:
                return RouteResult(
                    result=DeliveryResult.DELIVERED,
                    message_id=message.id,
                    detail=f"Routed to {recipient_id} for processing",
                    delivered_to=recipient_id,
                )
            else:
                return RouteResult(
                    result=DeliveryResult.QUEUED,
                    message_id=message.id,
                    detail=f"Recipient {recipient_id!r} not found — queued",
                    delivered_to=recipient_id,
                )

        else:
            # UNKNOWN or unclassified: route as direct
            if recipient_id in self._peers:
                return RouteResult(
                    result=DeliveryResult.DELIVERED,
                    message_id=message.id,
                    detail=f"Routed to {recipient_id} (unknown intent, treated as direct)",
                    delivered_to=recipient_id,
                )
            else:
                return RouteResult(
                    result=DeliveryResult.QUEUED,
                    message_id=message.id,
                    detail=f"Recipient {recipient_id!r} not found — queued",
                    delivered_to=recipient_id,
                )

    def _broadcast(self, message: MessageEnvelope, intent_str: str) -> RouteResult:
        """Fan out a broadcast message to all known peers."""
        if not self._peers:
            return RouteResult(
                result=DeliveryResult.FAILED,
                message_id=message.id,
                detail="Broadcast failed: no peers registered",
            )

        delivered_to = list(self._peers.keys())
        return RouteResult(
            result=DeliveryResult.DELIVERED,
            message_id=message.id,
            detail=f"Broadcast to {len(delivered_to)} peer(s): {', '.join(delivered_to)}",
            delivered_to=",".join(delivered_to),
        )

    # ── rate limiting ───────────────────────────────────────────────────

    def _check_rate(self, sender_id: str) -> bool:
        """Check if *sender_id* is within the rate limit.

        Returns True if the sender is allowed to send another message.
        """
        now_ms = int(time.time() * 1000)
        window_start = now_ms - self._rate_window_ms

        # Prune old timestamps
        bucket = self._rate_buckets[sender_id]
        self._rate_buckets[sender_id] = [ts for ts in bucket if ts > window_start]

        if len(self._rate_buckets[sender_id]) >= self._rate_limit:
            return False

        self._rate_buckets[sender_id].append(now_ms)
        return True

    def _rate_count(self, sender_id: str) -> int:
        """Return the current message count for *sender_id* in the rate window."""
        now_ms = int(time.time() * 1000)
        window_start = now_ms - self._rate_window_ms
        bucket = self._rate_buckets.get(sender_id, [])
        return sum(1 for ts in bucket if ts > window_start)
