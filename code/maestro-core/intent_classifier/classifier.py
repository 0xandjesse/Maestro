# nucleus/modules/intent_classifier/classifier.py
import re
import json
import uuid

from .interface import Intent, IntentResult, IntentClassifier
from .schema import Rule


# ACK patterns from the spec
_ACK_PATTERNS = [
    "Acknowledged", "Got it", "Roger", "Standing by", "Copy that",
    "ack", "ACK",
]

# Task language keywords for Subject: line detection
_TASK_KEYWORDS = [
    "task", "subtask", "complete", "done", "blocked", "report",
    "artifact", "build", "implement", "fix", "deploy", "test",
    "module", "contract", "deliver", "checklist",
]


def _compile_ack_regex() -> re.Pattern:
    escaped = [re.escape(p) for p in _ACK_PATTERNS]
    return re.compile(r"^\s*(?:" + "|".join(escaped) + r")\s*[.!]?\s*$")


def _compile_task_regex() -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(_TASK_KEYWORDS) + r")\b", re.IGNORECASE)


class DefaultIntentClassifier(IntentClassifier):
    """Concrete intent classifier with 6 default rules + dynamic rule support."""

    def __init__(self):
        self._rules: list[Rule] = []
        self._init_default_rules()

    def _init_default_rules(self) -> None:
        ack_re = _compile_ack_regex()
        task_re = _compile_task_regex()

        # msg_type rules take priority — checked first

        # Rule 5: msg_type == "directive" → WORK, reply
        self._rules.append(Rule(
            rule_id="default-directive",
            intent=Intent.WORK,
            should_reply=True,
            should_surface=True,
            condition=lambda content, msg_type: msg_type == "directive",
            description="Directive message type",
        ))

        # Rule 6: msg_type == "system" → SYSTEM, no reply
        self._rules.append(Rule(
            rule_id="default-system",
            intent=Intent.SYSTEM,
            should_reply=False,
            should_surface=False,
            condition=lambda content, msg_type: msg_type == "system",
            description="System message type",
        ))

        # Content-based rules

        # Rule 1: Content < 80 chars + matches ACK patterns → ACK, no reply
        self._rules.append(Rule(
            rule_id="default-ack",
            intent=Intent.ACK,
            should_reply=False,
            should_surface=False,
            pattern=ack_re,
            condition=lambda content, msg_type: len(content) < 80,
            description="Short ACK message detection",
        ))

        # Rule 2: Content starts with "Subject:" + contains task language → WORK, reply
        self._rules.append(Rule(
            rule_id="default-subject-task",
            intent=Intent.WORK,
            should_reply=True,
            should_surface=True,
            pattern=task_re,
            condition=lambda content, msg_type: content.strip().startswith("Subject:"),
            description="Subject line with task language",
        ))

        # Rule 3: Content is JSON with `status` field → STATUS, no reply
        self._rules.append(Rule(
            rule_id="default-json-status",
            intent=Intent.STATUS,
            should_reply=False,
            should_surface=False,
            condition=lambda content, msg_type: self._is_json_with_status(content),
            description="JSON payload with status field",
        ))

        # Rule 4: Content is health check → SYSTEM, no reply
        self._rules.append(Rule(
            rule_id="default-health-check",
            intent=Intent.SYSTEM,
            should_reply=False,
            should_surface=False,
            pattern=re.compile(r"\b(?:health.?check|ping|heartbeat|alive)\b", re.IGNORECASE),
            condition=lambda content, msg_type: len(content) < 200,
            description="Health check / ping message",
        ))

    @staticmethod
    def _is_json_with_status(content: str) -> bool:
        """Check if content is valid JSON containing a 'status' field."""
        try:
            data = json.loads(content)
            return isinstance(data, dict) and "status" in data
        except (json.JSONDecodeError, TypeError):
            return False

    def classify(self, content: str, msg_type: str = "direct") -> IntentResult:
        """Classify content by testing rules in priority order."""
        for rule in self._rules:
            if rule.matches(content, msg_type):
                return IntentResult(
                    intent=rule.intent,
                    confidence=1.0,
                    should_reply=rule.should_reply,
                    should_surface=rule.should_surface,
                    matched_rule=rule.rule_id,
                )

        # Fallthrough: UNKNOWN
        return IntentResult(
            intent=Intent.UNKNOWN,
            confidence=0.0,
            should_reply=False,
            should_surface=False,
            matched_rule="fallback-unknown",
        )

    def add_rule(self, pattern: str, intent: Intent, should_reply: bool, should_surface: bool) -> str:
        """Add a dynamic regex-based rule. Returns the rule ID."""
        rule_id = f"dynamic-{uuid.uuid4().hex[:8]}"
        compiled = re.compile(pattern)
        self._rules.append(Rule(
            rule_id=rule_id,
            intent=intent,
            should_reply=should_reply,
            should_surface=should_surface,
            pattern=compiled,
            description=f"Dynamic rule: {pattern}",
        ))
        return rule_id

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID. Returns True if found and removed."""
        for i, rule in enumerate(self._rules):
            if rule.rule_id == rule_id:
                self._rules.pop(i)
                return True
        return False
