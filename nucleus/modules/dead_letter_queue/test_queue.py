"""Module 11: Dead Letter Queue — Unit tests.

Covers: enqueue/dequeue, retry, purge, max retries, TTL expiry, notify sender.
"""

import time
import unittest

from nucleus.modules.dead_letter_queue.interface import DeadLetterQueue
from nucleus.modules.dead_letter_queue.queue import DeadLetterQueueImpl
from nucleus.modules.dead_letter_queue.schema import (
    DeadLetter,
    DeliveryResult,
    MessageEnvelope,
    generate_letter_id,
)


def _make_envelope(msg_id: str = "msg-1") -> MessageEnvelope:
    return MessageEnvelope(
        id=msg_id,
        type="direct",
        sender={"agentId": "alice"},
        recipient={"agentId": "bob"},
        content="test message",
        timestamp=int(time.time() * 1000),
        version="1.0",
    )


class TestEnqueueDequeue(unittest.TestCase):
    """Enqueue stores message with correct metadata; dequeue retrieves it."""

    def setUp(self) -> None:
        self.dlq: DeadLetterQueue = DeadLetterQueueImpl()

    def test_enqueue_returns_dead_letter_with_correct_fields(self) -> None:
        msg = _make_envelope()
        letter = self.dlq.enqueue(msg, "timeout", ttl=7200)

        self.assertIsInstance(letter, DeadLetter)
        self.assertTrue(letter.letter_id.startswith("dlq-"))
        self.assertEqual(letter.original_message, msg)
        self.assertEqual(letter.failure_reason, "timeout")
        self.assertEqual(letter.ttl, 7200)
        self.assertEqual(letter.retry_count, 0)
        self.assertEqual(letter.max_retries, 3)
        self.assertFalse(letter.sender_notified)
        self.assertGreater(letter.enqueued_at, 0)

    def test_enqueue_default_ttl(self) -> None:
        msg = _make_envelope()
        letter = self.dlq.enqueue(msg, "crash")
        self.assertEqual(letter.ttl, 3600)

    def test_dequeue_retrieves_by_letter_id(self) -> None:
        msg = _make_envelope()
        letter = self.dlq.enqueue(msg, "timeout")
        retrieved = self.dlq.dequeue(letter.letter_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.letter_id, letter.letter_id)  # type: ignore[union-attr]

    def test_dequeue_returns_none_for_unknown_id(self) -> None:
        result = self.dlq.dequeue("dlq-nonexistent")
        self.assertIsNone(result)

    def test_enqueue_multiple_letters_unique_ids(self) -> None:
        msg1 = _make_envelope("msg-1")
        msg2 = _make_envelope("msg-2")
        l1 = self.dlq.enqueue(msg1, "reason1")
        l2 = self.dlq.enqueue(msg2, "reason2")
        self.assertNotEqual(l1.letter_id, l2.letter_id)
        self.assertEqual(self.dlq.get_queue_size(), 2)


class TestRetry(unittest.TestCase):
    """Retry increments counter, returns result, enforces max retries."""

    def setUp(self) -> None:
        self.dlq: DeadLetterQueue = DeadLetterQueueImpl()

    def test_retry_increments_count_and_returns_delivered(self) -> None:
        msg = _make_envelope()
        letter = self.dlq.enqueue(msg, "timeout")
        result = self.dlq.retry(letter.letter_id)
        self.assertEqual(result, DeliveryResult.DELIVERED)

        updated = self.dlq.dequeue(letter.letter_id)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.retry_count, 1)  # type: ignore[union-attr]

    def test_retry_unknown_id_returns_failed(self) -> None:
        result = self.dlq.retry("dlq-ghost")
        self.assertEqual(result, DeliveryResult.FAILED)

    def test_max_retries_enforced_three_attempts_then_fail(self) -> None:
        msg = _make_envelope()
        letter = self.dlq.enqueue(msg, "timeout")

        # First 3 retries should succeed
        for i in range(3):
            result = self.dlq.retry(letter.letter_id)
            self.assertEqual(result, DeliveryResult.DELIVERED, f"retry {i+1} should succeed")

        # 4th retry should fail (retry_count == 3 == max_retries)
        result = self.dlq.retry(letter.letter_id)
        self.assertEqual(result, DeliveryResult.FAILED)

        updated = self.dlq.dequeue(letter.letter_id)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.retry_count, 3)  # type: ignore[union-attr]

    def test_retry_does_not_exceed_max_retries(self) -> None:
        msg = _make_envelope()
        letter = self.dlq.enqueue(msg, "timeout")
        # Retry 5 times — only first 3 should succeed
        results = [self.dlq.retry(letter.letter_id) for _ in range(5)]
        delivered = sum(1 for r in results if r == DeliveryResult.DELIVERED)
        failed = sum(1 for r in results if r == DeliveryResult.FAILED)
        self.assertEqual(delivered, 3)
        self.assertEqual(failed, 2)

        updated = self.dlq.dequeue(letter.letter_id)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.retry_count, 3)  # type: ignore[union-attr]


class TestPurge(unittest.TestCase):
    """Purge removes expired letters, returns count."""

    def setUp(self) -> None:
        self.dlq: DeadLetterQueue = DeadLetterQueueImpl()

    def test_purge_removes_expired_letters(self) -> None:
        msg = _make_envelope()
        # Enqueue with TTL=0 so it expires immediately
        letter = self.dlq.enqueue(msg, "timeout", ttl=0)
        # Small sleep to ensure clock has advanced
        time.sleep(0.01)

        purged = self.dlq.purge_expired()
        self.assertEqual(purged, 1)
        self.assertIsNone(self.dlq.dequeue(letter.letter_id))
        self.assertEqual(self.dlq.get_queue_size(), 0)

    def test_purge_keeps_non_expired_letters(self) -> None:
        msg = _make_envelope()
        # Enqueue with very long TTL
        letter = self.dlq.enqueue(msg, "timeout", ttl=99999)
        purged = self.dlq.purge_expired()
        self.assertEqual(purged, 0)
        self.assertIsNotNone(self.dlq.dequeue(letter.letter_id))

    def test_purge_mixed_expired_and_active(self) -> None:
        msg1 = _make_envelope("msg-1")
        msg2 = _make_envelope("msg-2")
        msg3 = _make_envelope("msg-3")

        self.dlq.enqueue(msg1, "r1", ttl=0)       # expired
        self.dlq.enqueue(msg2, "r2", ttl=99999)    # active
        self.dlq.enqueue(msg3, "r3", ttl=0)        # expired

        time.sleep(0.01)
        purged = self.dlq.purge_expired()
        self.assertEqual(purged, 2)
        self.assertEqual(self.dlq.get_queue_size(), 1)

    def test_purge_empty_queue_returns_zero(self) -> None:
        purged = self.dlq.purge_expired()
        self.assertEqual(purged, 0)


class TestTTLExpiry(unittest.TestCase):
    """TTL enforced — letters expire after TTL seconds."""

    def setUp(self) -> None:
        self.dlq: DeadLetterQueue = DeadLetterQueueImpl()

    def test_expired_letter_cannot_retry(self) -> None:
        msg = _make_envelope()
        letter = self.dlq.enqueue(msg, "timeout", ttl=0)
        time.sleep(0.01)

        result = self.dlq.retry(letter.letter_id)
        self.assertEqual(result, DeliveryResult.FAILED)

    def test_is_expired_property(self) -> None:
        msg = _make_envelope()
        letter = self.dlq.enqueue(msg, "timeout", ttl=0)
        time.sleep(0.01)
        self.assertTrue(letter.is_expired)

    def test_active_letter_is_not_expired(self) -> None:
        msg = _make_envelope()
        letter = self.dlq.enqueue(msg, "timeout", ttl=99999)
        self.assertFalse(letter.is_expired)

    def test_can_retry_false_when_expired(self) -> None:
        msg = _make_envelope()
        letter = self.dlq.enqueue(msg, "timeout", ttl=0)
        time.sleep(0.01)
        self.assertFalse(letter.can_retry)

    def test_can_retry_false_when_max_retries_reached(self) -> None:
        msg = _make_envelope()
        letter = self.dlq.enqueue(msg, "timeout", ttl=99999)
        for _ in range(3):
            self.dlq.retry(letter.letter_id)
        updated = self.dlq.dequeue(letter.letter_id)
        self.assertIsNotNone(updated)
        self.assertFalse(updated.can_retry)  # type: ignore[union-attr]


class TestNotifySender(unittest.TestCase):
    """Notify sender marks the flag on the stored letter."""

    def setUp(self) -> None:
        self.dlq: DeadLetterQueue = DeadLetterQueueImpl()

    def test_notify_sender_marks_flag_true(self) -> None:
        msg = _make_envelope()
        letter = self.dlq.enqueue(msg, "timeout")
        self.assertFalse(letter.sender_notified)

        result = self.dlq.notify_sender(letter)
        self.assertTrue(result)

        updated = self.dlq.dequeue(letter.letter_id)
        self.assertIsNotNone(updated)
        self.assertTrue(updated.sender_notified)  # type: ignore[union-attr]

    def test_notify_sender_unknown_letter_returns_false(self) -> None:
        ghost = DeadLetter(
            letter_id="dlq-ghost",
            original_message=_make_envelope(),
            failure_reason="nope",
            enqueued_at=int(time.time()),
        )
        result = self.dlq.notify_sender(ghost)
        self.assertFalse(result)

    def test_notify_sender_idempotent(self) -> None:
        msg = _make_envelope()
        letter = self.dlq.enqueue(msg, "timeout")
        self.dlq.notify_sender(letter)
        self.dlq.notify_sender(letter)  # second call
        updated = self.dlq.dequeue(letter.letter_id)
        self.assertIsNotNone(updated)
        self.assertTrue(updated.sender_notified)  # type: ignore[union-attr]


class TestBackoff(unittest.TestCase):
    """Exponential backoff: 2^retry_count seconds."""

    def setUp(self) -> None:
        self.dlq: DeadLetterQueue = DeadLetterQueueImpl()

    def test_backoff_increases_exponentially(self) -> None:
        msg = _make_envelope()
        letter = self.dlq.enqueue(msg, "timeout")
        self.assertEqual(letter.backoff_seconds, 1)  # 2^0

        self.dlq.retry(letter.letter_id)
        updated = self.dlq.dequeue(letter.letter_id)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.backoff_seconds, 2)  # type: ignore[union-attr]  # 2^1

        self.dlq.retry(letter.letter_id)
        updated = self.dlq.dequeue(letter.letter_id)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.backoff_seconds, 4)  # type: ignore[union-attr]  # 2^2

        self.dlq.retry(letter.letter_id)
        updated = self.dlq.dequeue(letter.letter_id)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.backoff_seconds, 8)  # type: ignore[union-attr]  # 2^3


class TestQueueSize(unittest.TestCase):
    """get_queue_size reflects current state."""

    def setUp(self) -> None:
        self.dlq: DeadLetterQueue = DeadLetterQueueImpl()

    def test_empty_queue_size_zero(self) -> None:
        self.assertEqual(self.dlq.get_queue_size(), 0)

    def test_size_increases_on_enqueue(self) -> None:
        self.dlq.enqueue(_make_envelope("m1"), "r1")
        self.assertEqual(self.dlq.get_queue_size(), 1)
        self.dlq.enqueue(_make_envelope("m2"), "r2")
        self.assertEqual(self.dlq.get_queue_size(), 2)

    def test_size_decreases_on_purge(self) -> None:
        self.dlq.enqueue(_make_envelope("m1"), "r1", ttl=0)
        time.sleep(0.01)
        self.dlq.purge_expired()
        self.assertEqual(self.dlq.get_queue_size(), 0)


class TestGenerateLetterId(unittest.TestCase):
    """Letter ID generation is unique and prefixed."""

    def test_generate_letter_id_prefix(self) -> None:
        lid = generate_letter_id()
        self.assertTrue(lid.startswith("dlq-"))

    def test_generate_letter_id_uniqueness(self) -> None:
        ids = {generate_letter_id() for _ in range(100)}
        self.assertEqual(len(ids), 100)


if __name__ == "__main__":
    unittest.main()
