# Module 11: Dead Letter Queue — Sub-spec
## Assigned to: Cee-Lo

### Interface Contract
```python
# nucleus/modules/dead_letter_queue/interface.py
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
    ttl: int = 3600                 # 1 hour default
    retry_count: int = 0
    max_retries: int = 3
    sender_notified: bool = False

class DeadLetterQueue:
    def enqueue(self, message: MessageEnvelope, reason: str, ttl: int = 3600) -> DeadLetter: ...
    def dequeue(self, letter_id: str) -> DeadLetter | None: ...
    def retry(self, letter_id: str) -> DeliveryResult: ...
    def purge_expired(self) -> int: ...  # returns count purged
    def get_queue_size(self) -> int: ...
    def notify_sender(self, letter: DeadLetter) -> bool: ...
```

### Key Behavior
- **Enqueue:** Store failed message with reason, TTL, and retry count. Auto-generate letter_id.
- **Dequeue:** Retrieve by letter_id, return None if not found
- **Retry:** Increment retry_count, attempt redelivery. If retry_count >= max_retries, mark as permanently failed.
- **Purge expired:** Remove letters where (enqueued_at + ttl) < now. Return count purged.
- **Notify sender:** Mark sender_notified = True. (In production this would send a message; for now, just track the flag.)
- **In-memory store** — no file I/O needed for this module
- **Exponential backoff:** retry_count used to calculate delay (2^retry_count seconds)

### Files to Create (absolute paths)
- `/home/andjesse/Projects/Maestro/nucleus/modules/dead_letter_queue/__init__.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/dead_letter_queue/interface.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/dead_letter_queue/queue.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/dead_letter_queue/schema.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/dead_letter_queue/test_queue.py`

### Dependencies
- Message Router (M1) — uses MessageEnvelope and DeliveryResult types. M1 is being built in parallel. Use the interface contract from `/home/andjesse/Projects/Maestro/nucleus/subspecs/module-01-message-router.md` as reference.

### Success Criteria
- Enqueue stores message with correct metadata
- Dequeue retrieves by letter_id
- Retry increments counter, returns result
- Purge removes expired letters
- Max retries enforced (3 attempts then permanent fail)
- TTL enforced (letters expire after TTL seconds)
- Unit tests: enqueue/dequeue, retry, purge, max retries, TTL expiry, notify sender
