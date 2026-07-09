"""Module 11: Dead Letter Queue — Schema types.

Uses MessageEnvelope and DeliveryResult from the M1 sub-spec contract.
These are defined here to avoid a circular dependency on M1 while M1 is
built in parallel.  Once M1 is stable, the types can be imported from
message_router.interface instead.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
import uuid


class DeliveryResult(Enum):
    DELIVERED = "delivered"
    FAILED = "failed"
    QUEUED = "queued"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


@dataclass
class MessageEnvelope:
    id: str
    type: str
    sender: dict
    recipient: dict
    content: str
    timestamp: int
    version: str
    intent: str | None = None
    inReplyTo: str | None = None
    stageId: str | None = None
    venueId: str | None = None
    ttl: int | None = None


@dataclass
class DeadLetter:
    letter_id: str
    original_message: MessageEnvelope
    failure_reason: str
    enqueued_at: int
    ttl: int = 3600
    retry_count: int = 0
    max_retries: int = 3
    sender_notified: bool = False

    @property
    def is_expired(self) -> bool:
        """True when (enqueued_at + ttl) <= now (TTL=0 expires immediately)."""
        return (self.enqueued_at + self.ttl) <= int(time.time())

    @property
    def can_retry(self) -> bool:
        """True when retry_count < max_retries and not expired."""
        return self.retry_count < self.max_retries and not self.is_expired

    @property
    def backoff_seconds(self) -> int:
        """Exponential backoff: 2^retry_count seconds."""
        return 2 ** self.retry_count


def generate_letter_id() -> str:
    """Generate a unique letter_id."""
    return f"dlq-{uuid.uuid4().hex[:12]}"
