"""Message Router — dedup, validation, intent-aware routing, rate limiting, broadcast.

Exports
-------
* ``DeliveryResult`` — enum of routing outcomes
* ``MessageEnvelope`` — dataclass for message envelopes
* ``RouteResult`` — dataclass for routing results
* ``MessageRouter`` — abstract interface
* ``InMemoryMessageRouter`` — in-memory implementation
* ``SeenSet`` — deduplication store
* ``validate_message`` — schema validator for message envelopes
"""

from .dedup import SeenSet
from .interface import DeliveryResult, MessageEnvelope, MessageRouter, RouteResult
from .router import InMemoryMessageRouter
from .schema import validate_message

__all__ = [
    "DeliveryResult",
    "InMemoryMessageRouter",
    "MessageEnvelope",
    "MessageRouter",
    "RouteResult",
    "SeenSet",
    "validate_message",
]
