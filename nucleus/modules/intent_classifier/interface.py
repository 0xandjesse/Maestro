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
    """Abstract interface for intent classification."""

    def classify(self, content: str, msg_type: str = "direct") -> IntentResult:
        raise NotImplementedError

    def add_rule(self, pattern: str, intent: Intent, should_reply: bool, should_surface: bool) -> str:
        raise NotImplementedError

    def remove_rule(self, rule_id: str) -> bool:
        raise NotImplementedError
