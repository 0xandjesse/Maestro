"""Module 11: Dead Letter Queue.

Stores failed messages with failure reason, TTL, and retry count.
Supports enqueue, dequeue, retry with exponential backoff, TTL-based
purge, and sender notification tracking.
"""

from .interface import DeadLetterQueue
from .queue import DeadLetterQueueImpl
from .schema import DeadLetter, DeliveryResult, MessageEnvelope, generate_letter_id

__all__ = [
    "DeadLetterQueue",
    "DeadLetterQueueImpl",
    "DeadLetter",
    "DeliveryResult",
    "MessageEnvelope",
    "generate_letter_id",
]
