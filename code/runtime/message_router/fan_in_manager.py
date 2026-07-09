# fan_in_manager.py — Fan-In Wait Manager (ADR-006 Phase 3)
# Tracks in-progress fan-in collections. Thread-safe.
# Used by the transport to wait for all fan-out branches to complete.

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from relay_evaluator import (
    RelayAction, RelayResult, merge_tokens, clone_token,
)


@dataclass
class FanInState:
    """Tracks one in-progress fan-in collection."""
    fan_in_node_id: str
    sources: list[str]                    # node IDs to wait for
    merge_strategy: str = "append"
    timeout_seconds: int = 3600
    on_timeout: str = "route_partial"
    next_node: str | None = None
    arrived: dict[str, dict] = field(default_factory=dict)  # source_node → token
    created_at: float = field(default_factory=time.time)
    timer_task: asyncio.Task | None = None


class FanInWaitManager:
    """Manages fan-in wait queues with timeout support.

    Thread-safe via asyncio.Lock. Designed to be a singleton on the transport.
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._waiting: dict[str, FanInState] = {}  # key: fan_in_node_id
        self._on_merge: Optional[callable] = None   # callback when merge fires
        self._on_timeout: Optional[callable] = None  # callback when timeout fires

    def set_callbacks(self, on_merge=None, on_timeout=None):
        """Set callbacks for merge and timeout events.
        on_merge(fan_in_node_id, merged_token, next_node)
        on_timeout(fan_in_node_id, partial_token, next_node, on_timeout_behavior)
        """
        self._on_merge = on_merge
        self._on_timeout = on_timeout

    async def register_arrival(self, fan_in_node_id: str, token: dict,
                               graph: dict) -> RelayResult:
        """Called when a token arrives at a fan-in node.

        Args:
            fan_in_node_id: The fan-in node ID
            token: The arriving token (from one branch)
            graph: The full workflow graph

        Returns:
            WAIT if still waiting, ADVANCE with merged token if all sources arrived
        """
        node = graph.get(fan_in_node_id, {})
        sources = node.get("sources", [])
        merge_strategy = node.get("merge_strategy", "append")
        timeout_seconds = node.get("timeout_seconds", 3600)
        on_timeout = node.get("on_timeout", "route_partial")
        next_node = node.get("next")

        source_id = token["meta"].get("fan_out_id", "unknown")

        async with self._lock:
            # Get or create state
            if fan_in_node_id not in self._waiting:
                state = FanInState(
                    fan_in_node_id=fan_in_node_id,
                    sources=sources,
                    merge_strategy=merge_strategy,
                    timeout_seconds=timeout_seconds,
                    on_timeout=on_timeout,
                    next_node=next_node,
                )
                # Start timeout timer
                state.timer_task = asyncio.create_task(
                    self._timeout_timer(fan_in_node_id, timeout_seconds)
                )
                self._waiting[fan_in_node_id] = state
            else:
                state = self._waiting[fan_in_node_id]

            # Register arrival
            state.arrived[source_id] = token

            # Check if all sources have arrived
            if len(state.arrived) >= len(sources):
                # All arrived — cancel timer, merge, clean up
                if state.timer_task:
                    state.timer_task.cancel()
                del self._waiting[fan_in_node_id]

                # Merge tokens
                all_tokens = list(state.arrived.values())
                merged = merge_tokens(all_tokens, strategy=merge_strategy)
                merged["meta"]["current_node"] = next_node or ""

                # Fire callback
                if self._on_merge:
                    await self._on_merge(fan_in_node_id, merged, next_node)

                return RelayResult(
                    RelayAction.ADVANCE, merged,
                    next_node=next_node,
                    reason=f"fan_in: all {len(sources)} sources arrived"
                )

            # Still waiting
            return RelayResult(
                RelayAction.WAIT, token,
                reason=f"fan_in: {len(state.arrived)}/{len(sources)} sources arrived"
            )

    async def _timeout_timer(self, fan_in_node_id: str, timeout_seconds: int):
        """Fire after timeout_seconds. Handles partial collection."""
        await asyncio.sleep(timeout_seconds)

        async with self._lock:
            state = self._waiting.pop(fan_in_node_id, None)
            if state is None:
                return  # already merged

            # Build partial token from whatever arrived
            if state.arrived:
                all_tokens = list(state.arrived.values())
                partial = merge_tokens(all_tokens, strategy=state.merge_strategy)
            else:
                partial = None

            on_timeout = state.on_timeout
            next_node = state.next_node

        # Fire callback outside lock
        if self._on_timeout:
            await self._on_timeout(fan_in_node_id, partial, next_node, on_timeout)

    async def get_state(self, fan_in_node_id: str) -> Optional[FanInState]:
        """Get current state of a fan-in collection (for debugging)."""
        async with self._lock:
            return self._waiting.get(fan_in_node_id)

    async def cancel(self, fan_in_node_id: str):
        """Cancel a fan-in wait (e.g., pipeline aborted)."""
        async with self._lock:
            state = self._waiting.pop(fan_in_node_id, None)
            if state and state.timer_task:
                state.timer_task.cancel()

    async def active_count(self) -> int:
        """Number of active fan-in waits."""
        async with self._lock:
            return len(self._waiting)
