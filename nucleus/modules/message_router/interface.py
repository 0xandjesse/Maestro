"""Message Router — Interface Contract.

Defines DeliveryResult, MessageEnvelope, RouteResult, and the MessageRouter
abstract base class that all implementations must satisfy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class DeliveryResult(Enum):
    DELIVERED = "delivered"
    FAILED = "failed"
    QUEUED = "queued"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


@dataclass
class MessageEnvelope:
    id: str
    type: str                        # "direct", "broadcast", "proxy", "system"
    sender: dict                     # {agentId, endpoint?}
    recipient: dict                  # {agentId, endpoint?}
    content: str
    timestamp: int                   # epoch ms
    version: str                     # protocol version
    intent: str | None = None        # "work" | "ack" | "query" | "status" — from Intent Classifier
    inReplyTo: str | None = None
    stageId: str | None = None
    venueId: str | None = None
    ttl: int | None = None


@dataclass
class RouteResult:
    result: DeliveryResult
    message_id: str
    detail: str | None = None
    delivered_to: str | None = None


class MessageRouter(ABC):
    """Abstract interface for message routing."""

    @abstractmethod
    def route(self, message: MessageEnvelope) -> RouteResult:
        """Route a message envelope to its destination.

        Parameters
        ----------
        message : MessageEnvelope
            The message to route.

        Returns
        -------
        RouteResult
            The result of the routing operation.
        """
        ...

    @abstractmethod
    def validate(self, message: MessageEnvelope) -> bool:
        """Validate a message envelope's required fields.

        Parameters
        ----------
        message : MessageEnvelope
            The message to validate.

        Returns
        -------
        bool
            True if the message passes validation.
        """
        ...

    @abstractmethod
    def get_seen_count(self) -> int:
        """Return the number of unique message IDs tracked in the dedup store.

        Returns
        -------
        int
            Count of seen message IDs.
        """
        ...
