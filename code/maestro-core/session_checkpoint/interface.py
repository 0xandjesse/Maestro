"""Session Checkpoint — Interface Contract.

Defines SessionState (the canonical checkpoint representation) and the
SessionCheckpoint abstract base class that all implementations must satisfy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SessionState:
    """Snapshot of an agent's session at a point in time."""

    agent_id: str
    session_id: str
    active_tasks: list[str] = field(default_factory=list)
    context_summary: str = ""
    last_message_id: str | None = None
    checkpointed_at: int = 0
    version: int = 1


class SessionCheckpoint(ABC):
    """Abstract interface for session checkpoint persistence.

    Implementations must provide save, restore, list, and prune operations
    with atomic writes and graceful handling of missing data.
    """

    @abstractmethod
    def save(self, agent_id: str, state: SessionState) -> str:
        """Persist *state* and return a checkpoint_id string."""
        ...

    @abstractmethod
    def restore(self, agent_id: str) -> SessionState | None:
        """Return the latest checkpoint for *agent_id*, or None."""
        ...

    @abstractmethod
    def list_checkpoints(self, agent_id: str) -> list[SessionState]:
        """Return all checkpoints for *agent_id*, newest first."""
        ...

    @abstractmethod
    def prune(self, agent_id: str, keep: int = 5) -> int:
        """Keep only the last *keep* checkpoints; return count pruned."""
        ...
