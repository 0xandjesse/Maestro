"""Module 11: Dead Letter Queue — Interface contract."""

from abc import ABC, abstractmethod

from .schema import DeadLetter, DeliveryResult, MessageEnvelope


class DeadLetterQueue(ABC):
    """Abstract interface for the Dead Letter Queue.

    Stores failed messages with metadata (reason, TTL, retry count).
    Supports enqueue, dequeue, retry, purge, and sender notification.
    """

    @abstractmethod
    def enqueue(self, message: MessageEnvelope, reason: str, ttl: int = 3600) -> DeadLetter:
        """Store a failed message with failure reason and TTL.

        Auto-generates a unique letter_id.
        """
        ...

    @abstractmethod
    def dequeue(self, letter_id: str) -> DeadLetter | None:
        """Retrieve a dead letter by its letter_id.

        Returns None if not found.
        """
        ...

    @abstractmethod
    def retry(self, letter_id: str) -> DeliveryResult:
        """Attempt redelivery of a dead letter.

        Increments retry_count.  If retry_count >= max_retries, marks as
        permanently failed (returns FAILED).  If the letter has expired,
        returns FAILED.  Otherwise simulates redelivery and returns
        DELIVERED.
        """
        ...

    @abstractmethod
    def purge_expired(self) -> int:
        """Remove all letters where (enqueued_at + ttl) < now.

        Returns the count of purged letters.
        """
        ...

    @abstractmethod
    def get_queue_size(self) -> int:
        """Return the current number of letters in the queue."""
        ...

    @abstractmethod
    def notify_sender(self, letter: DeadLetter) -> bool:
        """Mark sender_notified = True on the given letter.

        Returns True if the letter was found and marked, False otherwise.
        """
        ...
