# Module 6: Intent Classifier — Sub-spec
## Assigned to: Cee-Lo

### Interface Contract
```python
# nucleus/modules/intent_classifier/interface.py
from enum import Enum
from dataclasses import dataclass

class Intent(Enum):
    WORK = "work"
    ACK = "ack"
    QUERY = "query"
    STATUS = "status"
    SYSTEM = "system"
    UNKNOWN = "unknown"

@dataclass
class IntentResult:
    intent: Intent
    confidence: float
    should_reply: bool
    should_surface: bool
    matched_rule: str

class IntentClassifier:
    def classify(self, content: str, msg_type: str = "direct") -> IntentResult: ...
    def add_rule(self, pattern: str, intent: Intent, should_reply: bool, should_surface: bool) -> str: ...
    def remove_rule(self, rule_id: str) -> bool: ...
```

### Default Rules (hardcoded)
1. Content < 80 chars + matches ACK patterns → `ACK`, no reply
2. Content starts with "Subject:" + contains task language → `WORK`, reply
3. Content is JSON with `status` field → `STATUS`, no reply
4. Content is health check → `SYSTEM`, no reply
5. msg_type == "directive" → `WORK`, reply
6. msg_type == "system" → `SYSTEM`, no reply

### Files to Create
- `nucleus/modules/intent_classifier/__init__.py`
- `nucleus/modules/intent_classifier/interface.py`
- `nucleus/modules/intent_classifier/classifier.py`
- `nucleus/modules/intent_classifier/schema.py`
- `nucleus/modules/intent_classifier/test_classifier.py`

### Dependencies
None — fully independent.

### Success Criteria
- All 6 default rules implemented
- `classify()` returns correct IntentResult for each rule
- Unit tests pass for all rules
- ACK patterns: "Acknowledged", "Got it", "Roger", "Standing by", "Copy that", "ack", "ACK"
