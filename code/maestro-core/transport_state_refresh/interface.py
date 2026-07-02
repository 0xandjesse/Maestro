# Module 16: Transport State Refresh — Interface
# Dataclasses and abstract base class defining the contract.

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RefreshSignal:
    """A refresh signal sent to an agent."""

    agent_id: str
    signal_type: str  # "SIGHUP" | "REFRESH" | "CONFIG_CHANGE" | "TOKEN_UPDATE"
    timestamp: int
    payload: dict | None = None


@dataclass
class RefreshResult:
    """Result of a refresh operation for an agent."""

    agent_id: str
    ok: bool
    configs_reloaded: list[str] = field(default_factory=list)
    tokens_reloaded: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class TransportStateRefresh:
    """Abstract interface for transport state refresh operations."""

    def refresh(self, agent_id: str) -> RefreshResult:
        raise NotImplementedError

    def signal(self, agent_id: str, signal_type: str) -> bool:
        raise NotImplementedError

    def get_last_refresh(self, agent_id: str) -> int | None:
        raise NotImplementedError

    def is_stale(self, agent_id: str, max_age_seconds: int = 300) -> bool:
        raise NotImplementedError
