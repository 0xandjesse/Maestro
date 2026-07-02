# Module 1: Message Router — Sub-spec
## Assigned to: Cee-Lo

### Interface Contract
```python
# nucleus/modules/message_router/interface.py
from enum import Enum
from dataclasses import dataclass, field

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

class MessageRouter:
    def route(self, message: MessageEnvelope) -> RouteResult: ...
    def validate(self, message: MessageEnvelope) -> bool: ...
    def get_seen_count(self) -> int: ...
```

### Key Behavior
- **SeenSet dedup:** Track message IDs, reject duplicates within a window
- **Message validation:** Check required fields (id, type, sender, recipient, content, timestamp)
- **Intent-aware routing:** Use the `intent` field (set by Intent Classifier) to decide routing:
  - `ack` → accept, no reply
  - `work` → route to agent for processing
  - `query` → route, expect reply
  - `status` → log, no reply
  - `system` → process structurally, no LLM
- **Rate limiting:** Track messages per sender, reject if over threshold
- **Broadcast fanout:** When recipient is "broadcast" or "*", deliver to all known peers
- **In-memory store** — no file I/O needed for this module

### Files to Create (absolute paths)
- `/home/andjesse/Projects/Maestro/nucleus/modules/message_router/__init__.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/message_router/interface.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/message_router/router.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/message_router/dedup.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/message_router/schema.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/message_router/test_router.py`

### Dependencies
- Intent Classifier (M6) — already built at `/home/andjesse/Projects/Maestro/nucleus/modules/intent_classifier/`
- Import the IntentClassifier from M6 to classify messages before routing

### Success Criteria
- Valid messages route successfully
- Invalid messages rejected with reason
- Duplicate messages detected and rejected
- Intent-aware routing: ACK suppressed, WORK routed, SYSTEM processed
- Rate limiting blocks flood
- Broadcast fans out to all peers
- Unit tests: validation, dedup, intent routing, rate limiting, broadcast
