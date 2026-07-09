# Module 16: Transport State Refresh — Implementation
# In-memory transport state tracking with refresh signaling.

from __future__ import annotations

import time

from nucleus.modules.transport_state_refresh.interface import (
    RefreshResult,
    RefreshSignal,
    TransportStateRefresh,
)
from nucleus.modules.transport_state_refresh.schema import (
    DEFAULT_CONFIGS,
    DEFAULT_TOKENS,
    VALID_SIGNAL_TYPES,
)


class InMemoryTransportStateRefresh(TransportStateRefresh):
    """In-memory implementation of TransportStateRefresh.

    Tracks refresh state per agent using a dictionary store.
    No file I/O — purely in-memory.
    """

    def __init__(self) -> None:
        self._last_refresh: dict[str, int] = {}
        self._signals: dict[str, list[RefreshSignal]] = {}

    # ------------------------------------------------------------------
    # refresh
    # ------------------------------------------------------------------
    def refresh(self, agent_id: str) -> RefreshResult:
        """Simulate a config reload for an agent.

        Tracks which configs and tokens were reloaded.
        Returns a RefreshResult with the outcome.
        """
        now_ms = int(time.time() * 1000)
        errors: list[str] = []

        # Simulate config reload
        configs_reloaded: list[str] = list(DEFAULT_CONFIGS)
        tokens_reloaded: list[str] = list(DEFAULT_TOKENS)

        # Record the refresh timestamp
        self._last_refresh[agent_id] = now_ms

        # Record an implicit REFRESH signal
        signal = RefreshSignal(
            agent_id=agent_id,
            signal_type="REFRESH",
            timestamp=now_ms,
            payload={"configs": configs_reloaded, "tokens": tokens_reloaded},
        )
        self._signals.setdefault(agent_id, []).append(signal)

        return RefreshResult(
            agent_id=agent_id,
            ok=len(errors) == 0,
            configs_reloaded=configs_reloaded,
            tokens_reloaded=tokens_reloaded,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # signal
    # ------------------------------------------------------------------
    def signal(self, agent_id: str, signal_type: str) -> bool:
        """Record a refresh signal for an agent.

        Returns True if the signal was accepted (valid signal_type).
        Returns False if the signal_type is invalid.
        """
        if signal_type not in VALID_SIGNAL_TYPES:
            return False

        now_ms = int(time.time() * 1000)
        sig = RefreshSignal(
            agent_id=agent_id,
            signal_type=signal_type,
            timestamp=now_ms,
        )
        self._signals.setdefault(agent_id, []).append(sig)

        # A signal also updates the last-refresh timestamp
        self._last_refresh[agent_id] = now_ms

        return True

    # ------------------------------------------------------------------
    # get_last_refresh
    # ------------------------------------------------------------------
    def get_last_refresh(self, agent_id: str) -> int | None:
        """Return epoch ms of last refresh for agent, or None if never refreshed."""
        return self._last_refresh.get(agent_id)

    # ------------------------------------------------------------------
    # is_stale
    # ------------------------------------------------------------------
    def is_stale(self, agent_id: str, max_age_seconds: int = 300) -> bool:
        """Return True if agent hasn't been refreshed within max_age_seconds.

        An agent that has never been refreshed is considered stale.
        """
        last = self._last_refresh.get(agent_id)
        if last is None:
            return True

        now_ms = int(time.time() * 1000)
        age_seconds = (now_ms - last) / 1000.0
        return age_seconds > max_age_seconds

    # ------------------------------------------------------------------
    # helpers (for testing)
    # ------------------------------------------------------------------
    def _get_signals(self, agent_id: str) -> list[RefreshSignal]:
        """Return all signals recorded for an agent (testing helper)."""
        return list(self._signals.get(agent_id, []))
