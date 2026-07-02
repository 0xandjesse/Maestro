"""Gate Engine — in-memory implementation.

Evaluates TIME, DEPENDENCY, RESOURCE, and RATE gates against tokens.
Manages the token lifecycle state machine entirely in memory.
"""

from __future__ import annotations

import time
from collections import defaultdict

from .interface import (
    Gate,
    GateEngine,
    GateResult,
    GateType,
    TokenLifecycle,
)
from .schema import TERMINAL_STATES, validate_gate, validate_token


class InMemoryGateEngine(GateEngine):
    """In-memory gate engine with no file I/O.

    Stores tokens and gates in plain dicts.  Thread-safe for single-writer
    use; not safe for concurrent writers without external locking.
    """

    def __init__(self) -> None:
        self._tokens: dict[str, TokenLifecycle] = {}
        self._gates: dict[str, Gate] = {}
        # token_id → list of gate_ids
        self._token_gates: dict[str, list[str]] = defaultdict(list)
        # RATE tracking: token_id → epoch-ms timestamp of release
        self._release_timestamps: dict[str, int] = {}

    # ── public API ───────────────────────────────────────────────────

    def check_gates(self, token: TokenLifecycle) -> GateResult:
        """Evaluate all gates on *token*.  Returns the first blocking
        result or PASS."""
        gate_ids = self._token_gates.get(token.token_id, [])
        for gid in gate_ids:
            gate = self._gates.get(gid)
            if gate is None:
                continue
            result = self._evaluate_gate(gate, token)
            if result != GateResult.PASS:
                return result
        return GateResult.PASS

    def schedule_token(
        self,
        token_id: str,
        valid_after: int,
        valid_until: int | None = None,
    ) -> TokenLifecycle:
        """Create a token with a TIME gate.  State = 'scheduled'."""
        token = TokenLifecycle(
            token_id=token_id,
            state="scheduled",
            valid_after=valid_after,
            valid_until=valid_until,
            audit_trail=[{"action": "scheduled", "ts": self._now_ms()}],
        )
        self._tokens[token_id] = token

        # attach a TIME gate
        gate_id = f"time-{token_id}"
        gate = Gate(
            gate_id=gate_id,
            gate_type=GateType.TIME,
            config={
                "valid_after": valid_after,
                "valid_until": valid_until,
            },
            token_id=token_id,
        )
        self._gates[gate_id] = gate
        self._token_gates[token_id].append(gate_id)

        return token

    def add_dependency(self, token_id: str, depends_on: str) -> TokenLifecycle:
        """Add a dependency to *token_id*.  State moves to 'scheduled'
        if dependencies exist."""
        token = self._tokens.get(token_id)
        if token is None:
            # auto-create the token in created state, then add dep
            token = TokenLifecycle(
                token_id=token_id,
                state="created",
                audit_trail=[{"action": "created", "ts": self._now_ms()}],
            )
            self._tokens[token_id] = token

        if depends_on not in token.depends_on:
            token.depends_on.append(depends_on)

        # attach a DEPENDENCY gate (idempotent — one gate per token)
        dep_gate_id = f"dep-{token_id}"
        if dep_gate_id not in self._gates:
            gate = Gate(
                gate_id=dep_gate_id,
                gate_type=GateType.DEPENDENCY,
                config={"depends_on": token.depends_on},
                token_id=token_id,
            )
            self._gates[dep_gate_id] = gate
            self._token_gates[token_id].append(dep_gate_id)
        else:
            # update config with latest dependency list
            self._gates[dep_gate_id].config["depends_on"] = token.depends_on

        if token.depends_on:
            token.state = "scheduled"

        token.audit_trail.append({
            "action": "add_dependency",
            "depends_on": depends_on,
            "ts": self._now_ms(),
        })
        return token

    def release_token(self, token_id: str) -> TokenLifecycle:
        """Mark *token_id* as 'released' (ready for claiming)."""
        token = self._tokens.get(token_id)
        if token is None:
            raise KeyError(f"token {token_id!r} not found")

        token.state = "released"
        token.audit_trail.append({"action": "released", "ts": self._now_ms()})
        self._release_timestamps[token_id] = self._now_ms()
        return token

    def get_pending_tokens(self) -> list[TokenLifecycle]:
        """Return all tokens not in a terminal state."""
        return [
            t for t in self._tokens.values()
            if t.state not in TERMINAL_STATES
        ]

    # ── gate management (not in ABC, but useful for tests) ──────────

    def add_gate(self, gate: Gate) -> None:
        """Attach an arbitrary gate to its token."""
        self._gates[gate.gate_id] = gate
        if gate.token_id:
            self._token_gates[gate.token_id].append(gate.gate_id)

    def get_token(self, token_id: str) -> TokenLifecycle | None:
        """Return the stored token, or None."""
        return self._tokens.get(token_id)

    def set_token_state(self, token_id: str, state: str) -> TokenLifecycle:
        """Directly set a token's state (for test setup)."""
        token = self._tokens.get(token_id)
        if token is None:
            raise KeyError(f"token {token_id!r} not found")
        token.state = state
        token.audit_trail.append({
            "action": f"state→{state}",
            "ts": self._now_ms(),
        })
        return token

    # ── internal ────────────────────────────────────────────────────

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _evaluate_gate(self, gate: Gate, token: TokenLifecycle) -> GateResult:
        if gate.gate_type == GateType.TIME:
            return self._eval_time(gate, token)
        elif gate.gate_type == GateType.DEPENDENCY:
            return self._eval_dependency(gate, token)
        elif gate.gate_type == GateType.RESOURCE:
            return self._eval_resource(gate, token)
        elif gate.gate_type == GateType.RATE:
            return self._eval_rate(gate, token)
        return GateResult.PASS

    def _eval_time(self, gate: Gate, token: TokenLifecycle) -> GateResult:
        now = self._now_ms()
        valid_after = gate.config.get("valid_after")
        valid_until = gate.config.get("valid_until")

        if valid_after is not None and now < valid_after:
            return GateResult.BLOCK_NOT_YET
        if valid_until is not None and now > valid_until:
            return GateResult.BLOCK_EXPIRED
        return GateResult.PASS

    def _eval_dependency(self, gate: Gate, token: TokenLifecycle) -> GateResult:
        for dep_id in token.depends_on:
            dep_token = self._tokens.get(dep_id)
            if dep_token is None or dep_token.state != "completed":
                return GateResult.BLOCK_DEPENDENCY
        return GateResult.PASS

    def _eval_resource(self, gate: Gate, token: TokenLifecycle) -> GateResult:
        min_memory_mb = gate.config.get("min_memory_mb")
        max_cpu_pct = gate.config.get("max_cpu_pct")

        # Try psutil; fall back to always-pass if unavailable
        try:
            import psutil
        except ImportError:
            # No psutil — cannot enforce resource gates; pass through
            return GateResult.PASS

        if min_memory_mb is not None:
            avail_mb = psutil.virtual_memory().available / (1024 * 1024)
            if avail_mb < min_memory_mb:
                return GateResult.BLOCK_RESOURCE

        if max_cpu_pct is not None:
            cpu_pct = psutil.cpu_percent(interval=0.1)
            if cpu_pct > max_cpu_pct:
                return GateResult.BLOCK_RESOURCE

        return GateResult.PASS

    def _eval_rate(self, gate: Gate, token: TokenLifecycle) -> GateResult:
        max_per_minute = gate.config.get("max_per_minute")
        if max_per_minute is None:
            return GateResult.PASS

        now = self._now_ms()
        window_ms = 60_000
        cutoff = now - window_ms

        recent = sum(
            1 for ts in self._release_timestamps.values()
            if ts >= cutoff
        )
        if recent >= max_per_minute:
            return GateResult.BLOCK_RATE
        return GateResult.PASS
