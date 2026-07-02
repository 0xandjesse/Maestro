# nucleus/modules/intent_classifier/schema.py
"""Internal schema definitions for intent classifier rules."""

from dataclasses import dataclass, field
from typing import Optional, Callable
import re

from .interface import Intent


@dataclass
class Rule:
    """A single classification rule."""
    rule_id: str
    intent: Intent
    should_reply: bool
    should_surface: bool
    pattern: Optional[re.Pattern] = None
    condition: Optional[Callable[[str, str], bool]] = None
    description: str = ""

    def matches(self, content: str, msg_type: str) -> bool:
        """Check if this rule matches the given content and message type."""
        if self.condition and not self.condition(content, msg_type):
            return False
        if self.pattern:
            return bool(self.pattern.search(content))
        return True
