"""Module 11: Dead Letter Queue — In-memory implementation."""

import time
from collections import OrderedDict

from .interface import DeadLetterQueue
from .schema import DeadLetter, DeliveryResult, MessageEnvelope, generate_letter_id


class DeadLetterQueueImpl(DeadLetterQueue):
    """In-memory dead letter queue.

    Stores failed messages with failure reason, TTL, and retry count.
    Supports enqueue, dequeue, retry with exponential backoff, TTL-based
    purge, and sender notification tracking.
    """

    def __init__(self) -> None:
        self._letters: OrderedDict[str, DeadLetter] = OrderedDict()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, message: MessageEnvelope, reason: str, ttl: int = 3600) -> DeadLetter:
        """Store a failed message with failure reason and TTL.

        Auto-generates a unique letter_id.  Returns the created DeadLetter.
        """
        letter_id = generate_letter_id()
        letter = DeadLetter(
            letter_id=letter_id,
            original_message=message,
            failure_reason=reason,
            enqueued_at=int(time.time()),
            ttl=ttl,
            retry_count=0,
            max_retries=3,
            sender_notified=False,
        )
        self._letters[letter_id] = letter
        return letter

    def dequeue(self, letter_id: str) -> DeadLetter | None:
        """Retrieve a dead letter by its letter_id.

        Returns None if not found.  Does NOT remove the letter from the
        queue — use purge_expired() for removal.
        """
        return self._letters.get(letter_id)

    def retry(self, letter_id: str) -> DeliveryResult:
        """Attempt redelivery of a dead letter.

        - Returns FAILED if the letter is not found.
        - Returns FAILED if the letter has expired (enqueued_at + ttl < now).
        - Returns FAILED if retry_count >= max_retries (permanent failure).
        - Otherwise increments retry_count and returns DELIVERED.

        The exponential backoff delay (2^retry_count seconds) is calculated
        but not actually slept — callers should use letter.backoff_seconds
        to implement their own delay if needed.
        """
        letter = self._letters.get(letter_id)
        if letter is None:
            return DeliveryResult.FAILED

        if letter.is_expired:
            return DeliveryResult.FAILED

        if letter.retry_count >= letter.max_retries:
            return DeliveryResult.FAILED

        letter.retry_count += 1
        return DeliveryResult.DELIVERED

    def purge_expired(self) -> int:
        """Remove all letters where (enqueued_at + ttl) < now.

        Returns the count of purged letters.
        """
        expired_ids = [
            lid for lid, letter in self._letters.items() if letter.is_expired
        ]
        for lid in expired_ids:
            del self._letters[lid]
        return len(expired_ids)

    def get_queue_size(self) -> int:
        """Return the current number of letters in the queue."""
        return len(self._letters)

    def notify_sender(self, letter: DeadLetter) -> bool:
        """Mark sender_notified = True on the given letter.

        The letter must already be in the queue (matched by letter_id).
        Returns True if found and marked, False otherwise.
        """
        stored = self._letters.get(letter.letter_id)
        if stored is None:
            return False
        stored.sender_notified = True
        return True
