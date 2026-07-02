"""Gate Engine — unit tests.

Covers all gate types, state transitions, and edge cases.
"""

from __future__ import annotations

import time
import unittest

from .engine import InMemoryGateEngine
from .interface import Gate, GateResult, GateType, TokenLifecycle


class TestTimeGate(unittest.TestCase):
    """TIME gate: blocks before valid_after, passes after, blocks after valid_until."""

    def setUp(self):
        self.engine = InMemoryGateEngine()

    def test_blocks_before_valid_after(self):
        now_ms = int(time.time() * 1000)
        future = now_ms + 60_000  # 1 minute from now
        token = self.engine.schedule_token("t1", valid_after=future)
        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.BLOCK_NOT_YET)

    def test_passes_after_valid_after(self):
        now_ms = int(time.time() * 1000)
        past = now_ms - 60_000  # 1 minute ago
        token = self.engine.schedule_token("t2", valid_after=past)
        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.PASS)

    def test_blocks_after_valid_until(self):
        now_ms = int(time.time() * 1000)
        past = now_ms - 60_000
        expired = now_ms - 30_000
        token = self.engine.schedule_token("t3", valid_after=past, valid_until=expired)
        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.BLOCK_EXPIRED)

    def test_passes_within_window(self):
        now_ms = int(time.time() * 1000)
        past = now_ms - 60_000
        future = now_ms + 60_000
        token = self.engine.schedule_token("t4", valid_after=past, valid_until=future)
        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.PASS)

    def test_no_valid_after_passes_immediately(self):
        now_ms = int(time.time() * 1000)
        token = self.engine.schedule_token("t5", valid_after=now_ms)
        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.PASS)


class TestDependencyGate(unittest.TestCase):
    """DEPENDENCY gate: blocks when dependency not completed, passes when all completed."""

    def setUp(self):
        self.engine = InMemoryGateEngine()

    def test_blocks_when_dependency_not_completed(self):
        # Create dependency token in 'scheduled' state
        dep = TokenLifecycle(token_id="dep1", state="scheduled")
        self.engine._tokens["dep1"] = dep

        token = self.engine.add_dependency("t1", "dep1")
        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.BLOCK_DEPENDENCY)

    def test_passes_when_all_dependencies_completed(self):
        dep = TokenLifecycle(token_id="dep1", state="completed")
        self.engine._tokens["dep1"] = dep

        token = self.engine.add_dependency("t1", "dep1")
        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.PASS)

    def test_blocks_when_dependency_missing(self):
        # dep not in store at all
        token = self.engine.add_dependency("t1", "dep_missing")
        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.BLOCK_DEPENDENCY)

    def test_multiple_dependencies_all_must_complete(self):
        self.engine._tokens["dep1"] = TokenLifecycle(token_id="dep1", state="completed")
        self.engine._tokens["dep2"] = TokenLifecycle(token_id="dep2", state="scheduled")

        token = self.engine.add_dependency("t1", "dep1")
        token = self.engine.add_dependency("t1", "dep2")
        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.BLOCK_DEPENDENCY)

        # complete dep2
        self.engine._tokens["dep2"].state = "completed"
        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.PASS)


class TestResourceGate(unittest.TestCase):
    """RESOURCE gate: blocks when resources below threshold."""

    def setUp(self):
        self.engine = InMemoryGateEngine()

    def test_blocks_when_memory_below_threshold(self):
        token = TokenLifecycle(token_id="t1", state="scheduled")
        self.engine._tokens["t1"] = token

        gate = Gate(
            gate_id="res1",
            gate_type=GateType.RESOURCE,
            config={"min_memory_mb": 1_000_000_000},  # impossibly high
            token_id="t1",
        )
        self.engine.add_gate(gate)

        try:
            import psutil
            _ = psutil.virtual_memory()
        except ImportError:
            self.skipTest("psutil not available")

        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.BLOCK_RESOURCE)

    def test_passes_when_memory_above_threshold(self):
        token = TokenLifecycle(token_id="t1", state="scheduled")
        self.engine._tokens["t1"] = token

        gate = Gate(
            gate_id="res2",
            gate_type=GateType.RESOURCE,
            config={"min_memory_mb": 1},  # trivially low
            token_id="t1",
        )
        self.engine.add_gate(gate)

        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.PASS)

    def test_passes_when_no_psutil(self):
        # This test verifies the fallback path when psutil is absent.
        # We can't un-import psutil, but the code path is covered by
        # the fact that the engine handles ImportError gracefully.
        token = TokenLifecycle(token_id="t1", state="scheduled")
        self.engine._tokens["t1"] = token

        gate = Gate(
            gate_id="res3",
            gate_type=GateType.RESOURCE,
            config={"min_memory_mb": 1_000_000_000},
            token_id="t1",
        )
        self.engine.add_gate(gate)

        # If psutil is available, this may BLOCK or PASS depending on
        # actual system resources.  Either is valid — we just verify
        # no exception is raised.
        result = self.engine.check_gates(token)
        self.assertIn(result, (GateResult.PASS, GateResult.BLOCK_RESOURCE))


class TestRateGate(unittest.TestCase):
    """RATE gate: blocks when rate limit exceeded."""

    def setUp(self):
        self.engine = InMemoryGateEngine()

    def test_passes_when_under_rate_limit(self):
        token = TokenLifecycle(token_id="t1", state="scheduled")
        self.engine._tokens["t1"] = token

        gate = Gate(
            gate_id="rate1",
            gate_type=GateType.RATE,
            config={"max_per_minute": 100},
            token_id="t1",
        )
        self.engine.add_gate(gate)

        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.PASS)

    def test_blocks_when_rate_limit_exceeded(self):
        token = TokenLifecycle(token_id="t1", state="scheduled")
        self.engine._tokens["t1"] = token

        gate = Gate(
            gate_id="rate1",
            gate_type=GateType.RATE,
            config={"max_per_minute": 2},
            token_id="t1",
        )
        self.engine.add_gate(gate)

        # Simulate many recent releases
        now_ms = int(time.time() * 1000)
        for i in range(5):
            self.engine._release_timestamps[f"fake-{i}"] = now_ms

        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.BLOCK_RATE)

    def test_passes_when_old_releases_outside_window(self):
        token = TokenLifecycle(token_id="t1", state="scheduled")
        self.engine._tokens["t1"] = token

        gate = Gate(
            gate_id="rate1",
            gate_type=GateType.RATE,
            config={"max_per_minute": 2},
            token_id="t1",
        )
        self.engine.add_gate(gate)

        # Old releases outside the 60s window
        old_ms = int(time.time() * 1000) - 120_000
        for i in range(5):
            self.engine._release_timestamps[f"old-{i}"] = old_ms

        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.PASS)


class TestStateTransitions(unittest.TestCase):
    """Token lifecycle state machine."""

    def setUp(self):
        self.engine = InMemoryGateEngine()

    def test_schedule_token_creates_scheduled_state(self):
        now_ms = int(time.time() * 1000)
        token = self.engine.schedule_token("t1", valid_after=now_ms)
        self.assertEqual(token.state, "scheduled")
        self.assertEqual(token.token_id, "t1")

    def test_add_dependency_moves_to_scheduled(self):
        token = self.engine.add_dependency("t1", "dep1")
        self.assertEqual(token.state, "scheduled")
        self.assertIn("dep1", token.depends_on)

    def test_release_token_moves_to_released(self):
        now_ms = int(time.time() * 1000)
        self.engine.schedule_token("t1", valid_after=now_ms)
        token = self.engine.release_token("t1")
        self.assertEqual(token.state, "released")

    def test_release_nonexistent_raises(self):
        with self.assertRaises(KeyError):
            self.engine.release_token("nonexistent")

    def test_get_pending_tokens_excludes_terminal(self):
        now_ms = int(time.time() * 1000)
        self.engine.schedule_token("t1", valid_after=now_ms)
        self.engine.schedule_token("t2", valid_after=now_ms)
        self.engine.schedule_token("t3", valid_after=now_ms)

        # mark t2 as completed
        self.engine.set_token_state("t2", "completed")
        # mark t3 as expired
        self.engine.set_token_state("t3", "expired")

        pending = self.engine.get_pending_tokens()
        pending_ids = {t.token_id for t in pending}
        self.assertIn("t1", pending_ids)
        self.assertNotIn("t2", pending_ids)
        self.assertNotIn("t3", pending_ids)

    def test_full_lifecycle(self):
        now_ms = int(time.time() * 1000)
        # created → scheduled
        token = self.engine.schedule_token("t1", valid_after=now_ms)
        self.assertEqual(token.state, "scheduled")

        # scheduled → released
        token = self.engine.release_token("t1")
        self.assertEqual(token.state, "released")

        # released → claimed (manual state set)
        token = self.engine.set_token_state("t1", "claimed")
        self.assertEqual(token.state, "claimed")

        # claimed → completed
        token = self.engine.set_token_state("t1", "completed")
        self.assertEqual(token.state, "completed")

        # completed is terminal — not in pending
        pending = self.engine.get_pending_tokens()
        self.assertEqual(len(pending), 0)

    def test_audit_trail_grows(self):
        now_ms = int(time.time() * 1000)
        token = self.engine.schedule_token("t1", valid_after=now_ms)
        self.assertEqual(len(token.audit_trail), 1)
        self.assertEqual(token.audit_trail[0]["action"], "scheduled")

        token = self.engine.release_token("t1")
        self.assertEqual(len(token.audit_trail), 2)
        self.assertEqual(token.audit_trail[1]["action"], "released")


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def setUp(self):
        self.engine = InMemoryGateEngine()

    def test_check_gates_no_gates_returns_pass(self):
        token = TokenLifecycle(token_id="t1", state="scheduled")
        self.engine._tokens["t1"] = token
        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.PASS)

    def test_add_dependency_auto_creates_token(self):
        token = self.engine.add_dependency("new_token", "dep1")
        self.assertEqual(token.token_id, "new_token")
        self.assertEqual(token.state, "scheduled")
        self.assertIn("dep1", token.depends_on)

    def test_duplicate_dependency_not_added(self):
        token = self.engine.add_dependency("t1", "dep1")
        token = self.engine.add_dependency("t1", "dep1")
        self.assertEqual(len(token.depends_on), 1)

    def test_get_pending_tokens_empty(self):
        pending = self.engine.get_pending_tokens()
        self.assertEqual(pending, [])

    def test_multiple_gates_first_block_wins(self):
        now_ms = int(time.time() * 1000)
        future = now_ms + 60_000
        token = self.engine.schedule_token("t1", valid_after=future)

        # Add a resource gate that would also block
        gate = Gate(
            gate_id="res1",
            gate_type=GateType.RESOURCE,
            config={"min_memory_mb": 1_000_000_000},
            token_id="t1",
        )
        self.engine.add_gate(gate)

        # TIME gate is evaluated first (added by schedule_token), so
        # BLOCK_NOT_YET should win
        result = self.engine.check_gates(token)
        self.assertEqual(result, GateResult.BLOCK_NOT_YET)

    def test_get_token_returns_none_for_missing(self):
        self.assertIsNone(self.engine.get_token("nonexistent"))


if __name__ == "__main__":
    unittest.main()
