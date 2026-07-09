"""Tests for the Message Router module.

Covers:
* Message validation (required fields, invalid types)
* SeenSet deduplication
* Intent-aware routing (ACK, WORK, QUERY, STATUS, SYSTEM)
* Rate limiting
* Broadcast fanout
* Peer registration
"""

from __future__ import annotations

import time

import pytest

from nucleus.modules.message_router import (
    DeliveryResult,
    InMemoryMessageRouter,
    MessageEnvelope,
    SeenSet,
    validate_message,
)


# ── helpers ────────────────────────────────────────────────────────────


def _make_envelope(
    msg_id: str = "msg-001",
    msg_type: str = "direct",
    sender_id: str = "agent-sender",
    recipient_id: str = "agent-recipient",
    content: str = "Hello, world",
    intent: str | None = None,
    version: str = "1.0",
    **kwargs,
) -> MessageEnvelope:
    """Create a valid MessageEnvelope with sensible defaults."""
    return MessageEnvelope(
        id=msg_id,
        type=msg_type,
        sender={"agentId": sender_id},
        recipient={"agentId": recipient_id},
        content=content,
        timestamp=int(time.time() * 1000),
        version=version,
        intent=intent,
        **kwargs,
    )


# ── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def router():
    """Return a fresh InMemoryMessageRouter with two registered peers."""
    r = InMemoryMessageRouter()
    r.register_peer("agent-recipient")
    r.register_peer("agent-2")
    return r


@pytest.fixture
def seen_set():
    """Return a fresh SeenSet."""
    return SeenSet(max_size=100, ttl_ms=60_000)


# ═══════════════════════════════════════════════════════════════════════
#  Validation
# ═══════════════════════════════════════════════════════════════════════


class TestValidation:
    def test_valid_message_passes(self):
        msg = _make_envelope()
        errors = validate_message(msg)
        assert errors == []

    def test_missing_id(self):
        msg = _make_envelope(msg_id="")
        errors = validate_message(msg)
        assert any("id" in e for e in errors)

    def test_missing_type(self):
        msg = _make_envelope(msg_type="")
        errors = validate_message(msg)
        assert any("type" in e for e in errors)

    def test_invalid_type(self):
        msg = _make_envelope(msg_type="invalid_type")
        errors = validate_message(msg)
        assert any("type" in e for e in errors)

    def test_missing_sender_agent_id(self):
        msg = _make_envelope()
        msg.sender = {"endpoint": "foo"}
        errors = validate_message(msg)
        assert any("sender" in e for e in errors)

    def test_sender_not_dict(self):
        msg = _make_envelope()
        msg.sender = "not-a-dict"  # type: ignore[assignment]
        errors = validate_message(msg)
        assert any("sender" in e for e in errors)

    def test_missing_recipient_agent_id(self):
        msg = _make_envelope()
        msg.recipient = {"endpoint": "foo"}
        errors = validate_message(msg)
        assert any("recipient" in e for e in errors)

    def test_recipient_not_dict(self):
        msg = _make_envelope()
        msg.recipient = "not-a-dict"  # type: ignore[assignment]
        errors = validate_message(msg)
        assert any("recipient" in e for e in errors)

    def test_missing_content(self):
        msg = _make_envelope(content="")
        errors = validate_message(msg)
        assert any("content" in e for e in errors)

    def test_missing_timestamp(self):
        msg = _make_envelope()
        msg.timestamp = -1  # type: ignore[assignment]
        errors = validate_message(msg)
        assert any("timestamp" in e for e in errors)

    def test_missing_version(self):
        msg = _make_envelope(version="")
        errors = validate_message(msg)
        assert any("version" in e for e in errors)

    def test_invalid_intent(self):
        msg = _make_envelope(intent="flying")
        errors = validate_message(msg)
        assert any("intent" in e for e in errors)

    def test_invalid_in_reply_to(self):
        msg = _make_envelope(inReplyTo=123)  # type: ignore[arg-type]
        errors = validate_message(msg)
        assert any("inReplyTo" in e for e in errors)

    def test_invalid_ttl(self):
        msg = _make_envelope(ttl="forever")  # type: ignore[arg-type]
        errors = validate_message(msg)
        assert any("ttl" in e for e in errors)

    def test_router_validate_method(self, router):
        msg = _make_envelope()
        assert router.validate(msg) is True

    def test_router_validate_invalid(self, router):
        msg = _make_envelope(msg_id="")
        assert router.validate(msg) is False


# ═══════════════════════════════════════════════════════════════════════
#  SeenSet Deduplication
# ═══════════════════════════════════════════════════════════════════════


class TestSeenSet:
    def test_first_seen_not_duplicate(self, seen_set):
        assert seen_set.is_duplicate("msg-001") is False

    def test_second_seen_is_duplicate(self, seen_set):
        seen_set.is_duplicate("msg-001")
        assert seen_set.is_duplicate("msg-001") is True

    def test_different_ids_not_duplicates(self, seen_set):
        seen_set.is_duplicate("msg-001")
        assert seen_set.is_duplicate("msg-002") is False

    def test_count_increments(self, seen_set):
        assert seen_set.count() == 0
        seen_set.is_duplicate("msg-001")
        assert seen_set.count() == 1
        seen_set.is_duplicate("msg-002")
        assert seen_set.count() == 2
        # Duplicate doesn't increment
        seen_set.is_duplicate("msg-001")
        assert seen_set.count() == 2

    def test_clear(self, seen_set):
        seen_set.is_duplicate("msg-001")
        seen_set.is_duplicate("msg-002")
        seen_set.clear()
        assert seen_set.count() == 0
        assert seen_set.is_duplicate("msg-001") is False

    def test_max_size_eviction(self):
        ss = SeenSet(max_size=3, ttl_ms=None)
        ss.is_duplicate("a")
        ss.is_duplicate("b")
        ss.is_duplicate("c")
        assert ss.count() == 3
        # Adding a 4th should evict the oldest
        ss.is_duplicate("d")
        assert ss.count() == 3
        # "a" should be evicted (oldest)
        assert ss.is_duplicate("a") is False

    def test_ttl_expiry(self):
        ss = SeenSet(max_size=100, ttl_ms=1)  # 1ms TTL
        ss.is_duplicate("msg-001")
        assert ss.count() == 1
        time.sleep(0.01)  # 10ms — well past TTL
        # Next access should evict expired
        assert ss.is_duplicate("msg-001") is False
        assert ss.count() == 1  # re-added


# ═══════════════════════════════════════════════════════════════════════
#  Router — Dedup Integration
# ═══════════════════════════════════════════════════════════════════════


class TestRouterDedup:
    def test_duplicate_rejected(self, router):
        msg = _make_envelope(msg_id="dup-001")
        result1 = router.route(msg)
        assert result1.result == DeliveryResult.DELIVERED

        result2 = router.route(msg)
        assert result2.result == DeliveryResult.DUPLICATE
        assert "Duplicate" in (result2.detail or "")

    def test_seen_count_tracks(self, router):
        assert router.get_seen_count() == 0
        router.route(_make_envelope(msg_id="a"))
        assert router.get_seen_count() == 1
        router.route(_make_envelope(msg_id="b"))
        assert router.get_seen_count() == 2


# ═══════════════════════════════════════════════════════════════════════
#  Router — Validation Integration
# ═══════════════════════════════════════════════════════════════════════


class TestRouterValidation:
    def test_invalid_message_rejected(self, router):
        msg = _make_envelope(msg_id="")
        result = router.route(msg)
        assert result.result == DeliveryResult.REJECTED
        assert "Validation failed" in (result.detail or "")

    def test_missing_sender_rejected(self, router):
        msg = _make_envelope()
        msg.sender = {}
        result = router.route(msg)
        assert result.result == DeliveryResult.REJECTED


# ═══════════════════════════════════════════════════════════════════════
#  Intent-Aware Routing
# ═══════════════════════════════════════════════════════════════════════


class TestIntentRouting:
    def test_ack_accepted_no_reply(self, router):
        msg = _make_envelope(
            msg_id="ack-001",
            content="Acknowledged",
            intent="ack",
        )
        result = router.route(msg)
        assert result.result == DeliveryResult.DELIVERED
        assert "ACK" in (result.detail or "")

    def test_work_routed_to_peer(self, router):
        msg = _make_envelope(
            msg_id="work-001",
            content="Subject: Build module 1",
            intent="work",
        )
        result = router.route(msg)
        assert result.result == DeliveryResult.DELIVERED
        assert result.delivered_to == "agent-recipient"

    def test_work_queued_for_unknown_peer(self, router):
        msg = _make_envelope(
            msg_id="work-002",
            recipient_id="unknown-agent",
            content="Subject: Build module 1",
            intent="work",
        )
        result = router.route(msg)
        assert result.result == DeliveryResult.QUEUED
        assert "not found" in (result.detail or "")

    def test_query_routed_to_peer(self, router):
        msg = _make_envelope(
            msg_id="query-001",
            content="What is the status?",
            intent="query",
        )
        result = router.route(msg)
        assert result.result == DeliveryResult.DELIVERED
        assert result.delivered_to == "agent-recipient"

    def test_status_logged_no_reply(self, router):
        msg = _make_envelope(
            msg_id="status-001",
            content='{"status": "ok"}',
            intent="status",
        )
        result = router.route(msg)
        assert result.result == DeliveryResult.DELIVERED
        assert "Status" in (result.detail or "")

    def test_system_processed_structurally(self, router):
        msg = _make_envelope(
            msg_id="sys-001",
            msg_type="system",
            content="health check",
            intent="system",
        )
        result = router.route(msg)
        assert result.result == DeliveryResult.DELIVERED
        assert "System" in (result.detail or "")

    def test_unknown_intent_routed_as_direct(self, router):
        msg = _make_envelope(
            msg_id="unknown-001",
            content="Some random message",
            intent="unknown",
        )
        result = router.route(msg)
        assert result.result == DeliveryResult.DELIVERED
        assert result.delivered_to == "agent-recipient"

    def test_auto_classify_ack_content(self, router):
        """When intent is None, classifier should detect ACK from content."""
        msg = _make_envelope(
            msg_id="auto-ack-001",
            content="Acknowledged",
            intent=None,
        )
        result = router.route(msg)
        assert result.result == DeliveryResult.DELIVERED
        assert "ACK" in (result.detail or "")

    def test_auto_classify_directive(self, router):
        """When intent is None and content has Subject: + task language, classifier detects WORK."""
        msg = _make_envelope(
            msg_id="auto-work-001",
            msg_type="direct",
            content="Subject: Build the thing — task complete",
            intent=None,
        )
        result = router.route(msg)
        assert result.result == DeliveryResult.DELIVERED
        assert result.delivered_to == "agent-recipient"

    def test_auto_classify_system_type(self, router):
        """When intent is None and type is system, classifier should detect SYSTEM."""
        msg = _make_envelope(
            msg_id="auto-sys-001",
            msg_type="system",
            content="ping",
            intent=None,
        )
        result = router.route(msg)
        assert result.result == DeliveryResult.DELIVERED
        assert "System" in (result.detail or "")


# ═══════════════════════════════════════════════════════════════════════
#  Rate Limiting
# ═══════════════════════════════════════════════════════════════════════


class TestRateLimiting:
    def test_rate_limit_blocks_flood(self):
        r = InMemoryMessageRouter(rate_limit=3, rate_window_ms=60_000)
        r.register_peer("agent-recipient")

        for i in range(3):
            msg = _make_envelope(msg_id=f"rate-{i}", sender_id="flooder")
            result = r.route(msg)
            assert result.result == DeliveryResult.DELIVERED, f"msg {i} should deliver"

        # 4th message should be rate-limited
        msg = _make_envelope(msg_id="rate-3", sender_id="flooder")
        result = r.route(msg)
        assert result.result == DeliveryResult.REJECTED
        assert "Rate limit" in (result.detail or "")

    def test_different_senders_independent_limits(self):
        r = InMemoryMessageRouter(rate_limit=2, rate_window_ms=60_000)
        r.register_peer("agent-recipient")

        # Sender A hits limit
        for i in range(2):
            r.route(_make_envelope(msg_id=f"a-{i}", sender_id="sender-a"))
        result_a = r.route(_make_envelope(msg_id="a-2", sender_id="sender-a"))
        assert result_a.result == DeliveryResult.REJECTED

        # Sender B is unaffected
        result_b = r.route(_make_envelope(msg_id="b-0", sender_id="sender-b"))
        assert result_b.result == DeliveryResult.DELIVERED

    def test_rate_window_expires(self):
        r = InMemoryMessageRouter(rate_limit=2, rate_window_ms=1)  # 1ms window
        r.register_peer("agent-recipient")

        r.route(_make_envelope(msg_id="rw-0", sender_id="sender"))
        r.route(_make_envelope(msg_id="rw-1", sender_id="sender"))

        # Should be rate-limited now
        result = r.route(_make_envelope(msg_id="rw-2", sender_id="sender"))
        assert result.result == DeliveryResult.REJECTED

        # Wait for window to expire
        time.sleep(0.01)  # 10ms

        # Should be allowed again
        result = r.route(_make_envelope(msg_id="rw-3", sender_id="sender"))
        assert result.result == DeliveryResult.DELIVERED


# ═══════════════════════════════════════════════════════════════════════
#  Broadcast Fanout
# ═══════════════════════════════════════════════════════════════════════


class TestBroadcast:
    def test_broadcast_to_all_peers(self, router):
        msg = _make_envelope(
            msg_id="bcast-001",
            recipient_id="broadcast",
            content="All hands!",
        )
        result = router.route(msg)
        assert result.result == DeliveryResult.DELIVERED
        assert "Broadcast" in (result.detail or "")
        assert "agent-recipient" in (result.delivered_to or "")
        assert "agent-2" in (result.delivered_to or "")

    def test_broadcast_wildcard(self, router):
        msg = _make_envelope(
            msg_id="bcast-002",
            recipient_id="*",
            content="All hands!",
        )
        result = router.route(msg)
        assert result.result == DeliveryResult.DELIVERED
        assert "Broadcast" in (result.detail or "")

    def test_broadcast_no_peers_fails(self):
        r = InMemoryMessageRouter()  # no peers
        msg = _make_envelope(
            msg_id="bcast-003",
            recipient_id="broadcast",
            content="Hello?",
        )
        result = r.route(msg)
        assert result.result == DeliveryResult.FAILED
        assert "no peers" in (result.detail or "")


# ═══════════════════════════════════════════════════════════════════════
#  Peer Management
# ═══════════════════════════════════════════════════════════════════════


class TestPeerManagement:
    def test_register_peer(self, router):
        router.register_peer("agent-3")
        peers = router.get_peers()
        assert "agent-3" in peers

    def test_remove_peer(self, router):
        assert router.remove_peer("agent-recipient") is True
        assert "agent-recipient" not in router.get_peers()

    def test_remove_nonexistent_peer(self, router):
        assert router.remove_peer("nobody") is False

    def test_register_peer_with_endpoint(self, router):
        router.register_peer("agent-3", {"agentId": "agent-3", "endpoint": "tcp://localhost:9003"})
        peers = router.get_peers()
        assert peers["agent-3"]["endpoint"] == "tcp://localhost:9003"


# ═══════════════════════════════════════════════════════════════════════
#  Edge Cases
# ═══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_message_with_all_optional_fields(self, router):
        msg = _make_envelope(
            msg_id="full-001",
            intent="work",
            inReplyTo="msg-000",
            stageId="stage-1",
            venueId="venue-1",
            ttl=60000,
        )
        result = router.route(msg)
        assert result.result == DeliveryResult.DELIVERED

    def test_multiple_messages_different_ids(self, router):
        for i in range(5):
            msg = _make_envelope(msg_id=f"multi-{i}")
            result = router.route(msg)
            assert result.result == DeliveryResult.DELIVERED

    def test_seen_count_after_many_messages(self, router):
        for i in range(10):
            router.route(_make_envelope(msg_id=f"count-{i}"))
        assert router.get_seen_count() == 10

    def test_route_result_has_message_id(self, router):
        msg = _make_envelope(msg_id="result-id-test")
        result = router.route(msg)
        assert result.message_id == "result-id-test"
