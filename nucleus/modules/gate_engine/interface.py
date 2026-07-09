"""Gate Engine — Interface Contract.

Defines GateType, GateResult, Gate, TokenLifecycle, and the GateEngine
abstract base class that all implementations must satisfy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class GateType(Enum):
    TIME = "time"
    DEPENDENCY = "dependency"
    RESOURCE = "resource"
    RATE = "rate"


class GateResult(Enum):
    PASS = "pass"
    BLOCK_NOT_YET = "block_not_yet"
    BLOCK_EXPIRED = "block_expired"
    BLOCK_DEPENDENCY = "block_dependency"
    BLOCK_RESOURCE = "block_resource"
    BLOCK_RATE = "block_rate"


@dataclass
class Gate:
    gate_id: str
    gate_type: GateType
    config: dict                      # type-specific params
    token_id: str | None = None       # for dependency gates


@dataclass
class TokenLifecycle:
    token_id: str
    state: str                        # created → scheduled → released → claimed → completed | expired
    valid_after: int | None = None    # epoch ms
    valid_until: int | None = None
    depends_on: list[str] = field(default_factory=list)  # token IDs
    audit_trail: list[dict] = field(default_factory=list)


class GateEngine(ABC):
    """Abstract interface for the gate engine.

    Implementations must evaluate gates against tokens, manage the token
    lifecycle state machine, and provide pending-token visibility.
    """

    @abstractmethod
    def check_gates(self, token: TokenLifecycle) -> GateResult:
        """Evaluate all gates on *token*.  Returns the first blocking result
        or PASS if every gate clears."""
        ...

    @abstractmethod
    def schedule_token(
        self,
        token_id: str,
        valid_after: int,
        valid_until: int | None = None,
    ) -> TokenLifecycle:
        """Create a token with time gates.  State = 'scheduled'."""
        ...

    @abstractmethod
    def add_dependency(self, token_id: str, depends_on: str) -> TokenLifecycle:
        """Add a dependency to *token_id*.  State = 'scheduled' if
        dependencies exist."""
        ...

    @abstractmethod
    def release_token(self, token_id: str) -> TokenLifecycle:
        """Mark *token_id* as 'released' (ready for claiming)."""
        ...

    @abstractmethod
    def get_pending_tokens(self) -> list[TokenLifecycle]:
        """Return all tokens not in a terminal state (completed / expired)."""
        ...
