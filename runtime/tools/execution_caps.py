"""
Execution Caps — Hard termination limits for the AI agent loop.

Added to AIAgent as an optional ExecutionCaps instance. Breaching any
limit = hard termination (not warning). This is the safety valve.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULTS = {
    "officer": {"max_iterations": 150, "max_wall_clock_s": 1800, "max_tokens": 200_000, "max_cost_cents": 500},
    "worker": {"max_iterations": 50, "max_wall_clock_s": 1200, "max_tokens": 100_000, "max_cost_cents": 200},
}


@dataclass
class ExecutionCaps:
    """Mutable execution limits with runtime enforcement."""

    max_iterations: int = 90
    max_wall_clock_s: int = 1800
    max_tokens: int = 200_000
    max_cost_cents: int = 500

    # Runtime tracking (internal, not config)
    _start_time: Optional[float] = field(default=None, repr=False, compare=False)
    _token_total: int = field(default=0, repr=False, compare=False)
    _cost_total_cents: float = field(default=0.0, repr=False, compare=False)
    _iteration_count: int = field(default=0, repr=False, compare=False)
    _breached: bool = field(default=False, repr=False, compare=False)
    _breach_reason: Optional[str] = field(default=None, repr=False, compare=False)

    @classmethod
    def from_config(cls, role: str = "officer") -> "ExecutionCaps":
        """Load from config.yaml `agent.execution_caps`. Defaults by role."""
        defaults_data = DEFAULTS.get(role, DEFAULTS["worker"])
        config_caps = {}
        try:
            from hermes_cli.config import load_config
            config = load_config()
            config_caps = config.get("agent", {}).get("execution_caps", {})
        except Exception:
            pass  # Config not available
        return cls(
            max_iterations=config_caps.get("max_iterations", defaults_data["max_iterations"]),
            max_wall_clock_s=config_caps.get("max_wall_clock_s", defaults_data["max_wall_clock_s"]),
            max_tokens=config_caps.get("max_tokens", defaults_data["max_tokens"]),
            max_cost_cents=config_caps.get("max_cost_cents", defaults_data["max_cost_cents"]),
        )

    def start(self) -> None:
        self._start_time = time.monotonic()
        self._token_total = 0
        self._cost_total_cents = 0.0
        self._iteration_count = 0
        self._breached = False
        self._breach_reason = None

    def add_usage(self, prompt_tokens: int, completion_tokens: int, cost_cents: float = 0.0) -> None:
        self._token_total += prompt_tokens + completion_tokens
        self._cost_total_cents += cost_cents

    def increment_iteration(self) -> None:
        self._iteration_count += 1

    def is_breached(self) -> bool:
        if self._breached:
            return True
        if self._iteration_count >= self.max_iterations:
            self._breached = True
            self._breach_reason = f"iterations ({self._iteration_count}/{self.max_iterations})"
        elif self._start_time is not None and (time.monotonic() - self._start_time) >= self.max_wall_clock_s:
            self._breached = True
            self._breach_reason = f"wall_clock ({int(time.monotonic() - self._start_time)}s/{self.max_wall_clock_s}s)"
        elif self._token_total >= self.max_tokens:
            self._breached = True
            self._breach_reason = f"tokens ({self._token_total}/{self.max_tokens})"
        elif self._cost_total_cents >= self.max_cost_cents:
            self._breached = True
            self._breach_reason = f"cost ({self._cost_total_cents:.2f}c/{self.max_cost_cents}c)"
        if self._breached:
            logger.warning("Execution cap breached: %s", self._breach_reason)
        return self._breached

    @property
    def summary(self) -> Dict[str, Any]:
        return {
            "max_iterations": self.max_iterations,
            "iterations_used": self._iteration_count,
            "max_wall_clock_s": self.max_wall_clock_s,
            "wall_clock_elapsed_s": round(time.monotonic() - self._start_time, 1) if self._start_time else None,
            "max_tokens": self.max_tokens,
            "tokens_used": self._token_total,
            "max_cost_cents": self.max_cost_cents,
            "cost_used_cents": round(self._cost_total_cents, 4),
            "breached": self._breached,
            "breach_reason": self._breach_reason,
        }
