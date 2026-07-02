"""SeenSet deduplication for message IDs.

Tracks message IDs in a bounded in-memory set with optional TTL-based
eviction.  Rejects duplicates within the tracking window.
"""

from __future__ import annotations

import time


class SeenSet:
    """In-memory deduplication store for message IDs.

    Tracks seen message IDs and their arrival timestamps.  Supports
    optional TTL-based eviction to bound memory usage.

    Parameters
    ----------
    max_size : int
        Maximum number of entries before oldest are evicted.
    ttl_ms : int | None
        Time-to-live in milliseconds.  Entries older than this are
        considered expired and removed on access.  None = no TTL.
    """

    def __init__(self, max_size: int = 10_000, ttl_ms: int | None = 300_000) -> None:
        self._max_size = max_size
        self._ttl_ms = ttl_ms
        self._seen: dict[str, int] = {}  # msg_id -> arrival_timestamp_ms

    def is_duplicate(self, message_id: str) -> bool:
        """Check if *message_id* has already been seen.

        If the ID is present and not expired, returns True.
        Otherwise records the ID and returns False.

        Parameters
        ----------
        message_id : str
            The message ID to check.

        Returns
        -------
        bool
            True if the message is a duplicate.
        """
        self._evict_expired()

        if message_id in self._seen:
            return True

        self._add(message_id)
        return False

    def _add(self, message_id: str) -> None:
        """Record a new message ID, evicting oldest if at capacity."""
        now_ms = int(time.time() * 1000)

        if len(self._seen) >= self._max_size:
            # Evict the oldest entry
            oldest_id = min(self._seen, key=lambda k: self._seen[k])
            del self._seen[oldest_id]

        self._seen[message_id] = now_ms

    def _evict_expired(self) -> None:
        """Remove entries older than TTL."""
        if self._ttl_ms is None:
            return

        now_ms = int(time.time() * 1000)
        expired = [
            mid
            for mid, ts in self._seen.items()
            if now_ms - ts > self._ttl_ms
        ]
        for mid in expired:
            del self._seen[mid]

    def count(self) -> int:
        """Return the number of tracked message IDs."""
        self._evict_expired()
        return len(self._seen)

    def clear(self) -> None:
        """Remove all tracked message IDs."""
        self._seen.clear()
