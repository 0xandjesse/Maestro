# nucleus/modules/intent_classifier/test_classifier.py
"""Unit tests for the intent classifier module."""

import json
import pytest
from .interface import Intent, IntentResult
from .classifier import DefaultIntentClassifier


@pytest.fixture
def classifier():
    return DefaultIntentClassifier()


# ── Rule 1: ACK detection ──────────────────────────────────────────

ACK_CASES = [
    "Acknowledged",
    "Got it",
    "Roger",
    "Standing by",
    "Copy that",
    "ack",
    "ACK",
    "Acknowledged.",
    "  Roger  ",
    "Got it!",
]


@pytest.mark.parametrize("content", ACK_CASES)
def test_rule1_ack_detection(classifier, content):
    """Rule 1: Content < 80 chars + matches ACK patterns → ACK, no reply."""
    result = classifier.classify(content, msg_type="direct")
    assert result.intent == Intent.ACK
    assert result.should_reply is False
    assert result.should_surface is False
    assert result.matched_rule == "default-ack"


def test_rule1_ack_long_content_no_match(classifier):
    """ACK patterns in long content should NOT match rule 1."""
    long_msg = "Acknowledged " + "x" * 80
    result = classifier.classify(long_msg, msg_type="direct")
    # Should not match rule 1 (too long), should fall through
    assert result.matched_rule != "default-ack"


# ── Rule 2: Subject line with task language ─────────────────────────

SUBJECT_TASK_CASES = [
    "Subject: Task complete — auth module built",
    "Subject: Subtask 1/3 done",
    "Subject: Build report for module 6",
    "Subject: Implement fix for bug #42",
    "Subject: Deploy checklist item 3",
]


@pytest.mark.parametrize("content", SUBJECT_TASK_CASES)
def test_rule2_subject_task(classifier, content):
    """Rule 2: Content starts with 'Subject:' + task language → WORK, reply."""
    result = classifier.classify(content, msg_type="direct")
    assert result.intent == Intent.WORK
    assert result.should_reply is True
    assert result.should_surface is True
    assert result.matched_rule == "default-subject-task"


def test_rule2_subject_no_task_language(classifier):
    """Subject line without task keywords should not match rule 2."""
    result = classifier.classify("Subject: Hello there", msg_type="direct")
    assert result.matched_rule != "default-subject-task"


# ── Rule 3: JSON with status field ──────────────────────────────────

def test_rule3_json_status(classifier):
    """Rule 3: JSON with 'status' field → STATUS, no reply."""
    payload = json.dumps({"status": "in_progress", "task_id": "abc"})
    result = classifier.classify(payload, msg_type="direct")
    assert result.intent == Intent.STATUS
    assert result.should_reply is False
    assert result.should_surface is False
    assert result.matched_rule == "default-json-status"


def test_rule3_json_no_status_field(classifier):
    """JSON without 'status' field should not match rule 3."""
    payload = json.dumps({"data": "hello"})
    result = classifier.classify(payload, msg_type="direct")
    assert result.matched_rule != "default-json-status"


def test_rule3_not_json(classifier):
    """Non-JSON content should not match rule 3."""
    result = classifier.classify("not json at all", msg_type="direct")
    assert result.matched_rule != "default-json-status"


# ── Rule 4: Health check ────────────────────────────────────────────

HEALTH_CHECK_CASES = [
    "health check",
    "HEALTHCHECK",
    "ping",
    "PING",
    "heartbeat",
    "alive?",
    "system health check ok",
]


@pytest.mark.parametrize("content", HEALTH_CHECK_CASES)
def test_rule4_health_check(classifier, content):
    """Rule 4: Health check → SYSTEM, no reply."""
    result = classifier.classify(content, msg_type="direct")
    assert result.intent == Intent.SYSTEM
    assert result.should_reply is False
    assert result.should_surface is False
    assert result.matched_rule == "default-health-check"


def test_rule4_health_check_long_content_no_match(classifier):
    """Health check in long content should not match rule 4."""
    long_msg = "health check " + "x" * 200
    result = classifier.classify(long_msg, msg_type="direct")
    assert result.matched_rule != "default-health-check"


# ── Rule 5: Directive message type ──────────────────────────────────

def test_rule5_directive(classifier):
    """Rule 5: msg_type == 'directive' → WORK, reply."""
    result = classifier.classify("any content here", msg_type="directive")
    assert result.intent == Intent.WORK
    assert result.should_reply is True
    assert result.should_surface is True
    assert result.matched_rule == "default-directive"


# ── Rule 6: System message type ─────────────────────────────────────

def test_rule6_system(classifier):
    """Rule 6: msg_type == 'system' → SYSTEM, no reply."""
    result = classifier.classify("any content here", msg_type="system")
    assert result.intent == Intent.SYSTEM
    assert result.should_reply is False
    assert result.should_surface is False
    assert result.matched_rule == "default-system"


# ── Rule ordering: directive/system take priority over content ──────

def test_directive_overrides_ack_pattern(classifier):
    """A directive that looks like an ACK should still be WORK."""
    result = classifier.classify("Acknowledged", msg_type="directive")
    assert result.intent == Intent.WORK
    assert result.matched_rule == "default-directive"


def test_system_overrides_subject_task(classifier):
    """A system message with Subject: should still be SYSTEM."""
    result = classifier.classify("Subject: task complete", msg_type="system")
    assert result.intent == Intent.SYSTEM
    assert result.matched_rule == "default-system"


# ── Fallthrough: UNKNOWN ────────────────────────────────────────────

def test_fallback_unknown(classifier):
    """Content matching no rules → UNKNOWN."""
    result = classifier.classify("random chatter about the weather", msg_type="direct")
    assert result.intent == Intent.UNKNOWN
    assert result.confidence == 0.0
    assert result.should_reply is False
    assert result.should_surface is False
    assert result.matched_rule == "fallback-unknown"


# ── Dynamic rules ───────────────────────────────────────────────────

def test_add_and_use_dynamic_rule(classifier):
    """Dynamic rules should be evaluated after default rules."""
    rule_id = classifier.add_rule(r"^URGENT:", Intent.WORK, True, True)
    assert rule_id.startswith("dynamic-")

    result = classifier.classify("URGENT: server down", msg_type="direct")
    assert result.intent == Intent.WORK
    assert result.should_reply is True
    assert result.should_surface is True
    assert result.matched_rule == rule_id


def test_remove_dynamic_rule(classifier):
    """Removing a dynamic rule should work."""
    rule_id = classifier.add_rule(r"^TEST:", Intent.QUERY, False, False)
    assert classifier.remove_rule(rule_id) is True
    assert classifier.remove_rule(rule_id) is False  # already gone


def test_remove_nonexistent_rule(classifier):
    """Removing a nonexistent rule returns False."""
    assert classifier.remove_rule("nonexistent-id") is False


# ── Confidence values ───────────────────────────────────────────────

def test_confidence_is_1_for_matched_rules(classifier):
    """All matched rules should return confidence 1.0."""
    result = classifier.classify("Acknowledged", msg_type="direct")
    assert result.confidence == 1.0


# ── Edge cases ──────────────────────────────────────────────────────

def test_empty_content(classifier):
    """Empty content should fall through to UNKNOWN."""
    result = classifier.classify("", msg_type="direct")
    assert result.intent == Intent.UNKNOWN


def test_whitespace_only(classifier):
    """Whitespace-only content should fall through to UNKNOWN."""
    result = classifier.classify("   \n  \t  ", msg_type="direct")
    assert result.intent == Intent.UNKNOWN
