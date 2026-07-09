# Module 16: Transport State Refresh — Unit Tests

from __future__ import annotations

import time
import unittest

from nucleus.modules.transport_state_refresh.interface import (
    RefreshResult,
    RefreshSignal,
)
from nucleus.modules.transport_state_refresh.refresh import (
    InMemoryTransportStateRefresh,
)
from nucleus.modules.transport_state_refresh.schema import (
    DEFAULT_CONFIGS,
    DEFAULT_TOKENS,
    VALID_SIGNAL_TYPES,
)


class TestTransportStateRefresh(unittest.TestCase):
    """Unit tests for InMemoryTransportStateRefresh."""

    def setUp(self) -> None:
        self.tsr = InMemoryTransportStateRefresh()

    # ------------------------------------------------------------------
    # refresh
    # ------------------------------------------------------------------
    def test_refresh_returns_correct_agent_id(self) -> None:
        result = self.tsr.refresh("agent-1")
        self.assertEqual(result.agent_id, "agent-1")

    def test_refresh_returns_ok_true(self) -> None:
        result = self.tsr.refresh("agent-1")
        self.assertTrue(result.ok)

    def test_refresh_reloads_default_configs(self) -> None:
        result = self.tsr.refresh("agent-1")
        self.assertEqual(result.configs_reloaded, DEFAULT_CONFIGS)

    def test_refresh_reloads_default_tokens(self) -> None:
        result = self.tsr.refresh("agent-1")
        self.assertEqual(result.tokens_reloaded, DEFAULT_TOKENS)

    def test_refresh_has_no_errors(self) -> None:
        result = self.tsr.refresh("agent-1")
        self.assertEqual(result.errors, [])

    def test_refresh_updates_last_refresh_timestamp(self) -> None:
        before = int(time.time() * 1000)
        self.tsr.refresh("agent-1")
        after = int(time.time() * 1000)
        ts = self.tsr.get_last_refresh("agent-1")
        self.assertIsNotNone(ts)
        self.assertGreaterEqual(ts, before)
        self.assertLessEqual(ts, after)

    # ------------------------------------------------------------------
    # signal
    # ------------------------------------------------------------------
    def test_signal_valid_type_returns_true(self) -> None:
        for st in VALID_SIGNAL_TYPES:
            with self.subTest(signal_type=st):
                result = self.tsr.signal("agent-1", st)
                self.assertTrue(result)

    def test_signal_invalid_type_returns_false(self) -> None:
        result = self.tsr.signal("agent-1", "BOGUS")
        self.assertFalse(result)

    def test_signal_updates_last_refresh(self) -> None:
        self.tsr.signal("agent-1", "SIGHUP")
        ts = self.tsr.get_last_refresh("agent-1")
        self.assertIsNotNone(ts)

    def test_signal_records_signal_internally(self) -> None:
        self.tsr.signal("agent-1", "CONFIG_CHANGE")
        signals = self.tsr._get_signals("agent-1")
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal_type, "CONFIG_CHANGE")
        self.assertEqual(signals[0].agent_id, "agent-1")

    # ------------------------------------------------------------------
    # get_last_refresh
    # ------------------------------------------------------------------
    def test_get_last_refresh_returns_none_for_unknown_agent(self) -> None:
        result = self.tsr.get_last_refresh("no-such-agent")
        self.assertIsNone(result)

    def test_get_last_refresh_returns_timestamp_after_refresh(self) -> None:
        self.tsr.refresh("agent-1")
        ts = self.tsr.get_last_refresh("agent-1")
        self.assertIsInstance(ts, int)
        self.assertGreater(ts, 0)

    def test_get_last_refresh_returns_timestamp_after_signal(self) -> None:
        self.tsr.signal("agent-1", "TOKEN_UPDATE")
        ts = self.tsr.get_last_refresh("agent-1")
        self.assertIsInstance(ts, int)
        self.assertGreater(ts, 0)

    # ------------------------------------------------------------------
    # is_stale
    # ------------------------------------------------------------------
    def test_is_stale_returns_true_for_unknown_agent(self) -> None:
        self.assertTrue(self.tsr.is_stale("no-such-agent"))

    def test_is_stale_returns_false_immediately_after_refresh(self) -> None:
        self.tsr.refresh("agent-1")
        self.assertFalse(self.tsr.is_stale("agent-1"))

    def test_is_stale_returns_false_immediately_after_signal(self) -> None:
        self.tsr.signal("agent-1", "REFRESH")
        self.assertFalse(self.tsr.is_stale("agent-1"))

    def test_is_stale_respects_max_age_seconds(self) -> None:
        # Artificially set a very old timestamp
        old_ts = int((time.time() - 600) * 1000)  # 600 seconds ago
        self.tsr._last_refresh["agent-old"] = old_ts
        self.assertTrue(self.tsr.is_stale("agent-old", max_age_seconds=300))
        self.assertFalse(self.tsr.is_stale("agent-old", max_age_seconds=900))

    # ------------------------------------------------------------------
    # multiple agents
    # ------------------------------------------------------------------
    def test_multiple_agents_independent_state(self) -> None:
        self.tsr.refresh("agent-A")
        self.tsr.signal("agent-B", "SIGHUP")

        self.assertIsNotNone(self.tsr.get_last_refresh("agent-A"))
        self.assertIsNotNone(self.tsr.get_last_refresh("agent-B"))
        self.assertIsNone(self.tsr.get_last_refresh("agent-C"))

    def test_multiple_agents_different_timestamps(self) -> None:
        self.tsr.refresh("agent-A")
        time.sleep(0.01)
        self.tsr.refresh("agent-B")

        ts_a = self.tsr.get_last_refresh("agent-A")
        ts_b = self.tsr.get_last_refresh("agent-B")
        self.assertIsNotNone(ts_a)
        self.assertIsNotNone(ts_b)
        self.assertLess(ts_a, ts_b)

    # ------------------------------------------------------------------
    # edge cases
    # ------------------------------------------------------------------
    def test_refresh_twice_updates_timestamp(self) -> None:
        self.tsr.refresh("agent-1")
        ts1 = self.tsr.get_last_refresh("agent-1")
        time.sleep(0.01)
        self.tsr.refresh("agent-1")
        ts2 = self.tsr.get_last_refresh("agent-1")
        self.assertGreater(ts2, ts1)

    def test_signal_multiple_types_for_same_agent(self) -> None:
        for st in VALID_SIGNAL_TYPES:
            self.tsr.signal("agent-1", st)
        signals = self.tsr._get_signals("agent-1")
        self.assertEqual(len(signals), len(VALID_SIGNAL_TYPES))
        recorded_types = [s.signal_type for s in signals]
        for st in VALID_SIGNAL_TYPES:
            self.assertIn(st, recorded_types)

    def test_refresh_result_is_dataclass(self) -> None:
        result = self.tsr.refresh("agent-1")
        self.assertIsInstance(result, RefreshResult)

    def test_signal_preserves_agent_id(self) -> None:
        self.tsr.signal("unique-agent-42", "REFRESH")
        signals = self.tsr._get_signals("unique-agent-42")
        self.assertEqual(signals[0].agent_id, "unique-agent-42")

    def test_is_stale_default_max_age(self) -> None:
        self.tsr.refresh("agent-1")
        self.assertFalse(self.tsr.is_stale("agent-1"))  # default 300s

    def test_empty_agent_id_works(self) -> None:
        result = self.tsr.refresh("")
        self.assertEqual(result.agent_id, "")
        self.assertTrue(result.ok)
        self.assertIsNotNone(self.tsr.get_last_refresh(""))


if __name__ == "__main__":
    unittest.main()
