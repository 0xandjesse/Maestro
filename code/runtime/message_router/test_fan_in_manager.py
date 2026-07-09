# test_fan_in_manager.py — Unit tests for fan_in_manager.py

import asyncio
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fan_in_manager import FanInWaitManager, FanInState
from relay_evaluator import RelayAction, new_token, clone_token


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

def _make_graph(sources=None, merge_strategy="append", timeout_seconds=3600,
                on_timeout="route_partial", next_node="after_fan_in"):
    if sources is None:
        sources = ["branch_a", "branch_b"]
    return {
        "fan_in": {
            "type": "fan_in",
            "sources": sources,
            "merge_strategy": merge_strategy,
            "timeout_seconds": timeout_seconds,
            "on_timeout": on_timeout,
            "next": next_node,
        },
        "after_fan_in": {"type": "phase", "agent": "proteus", "work_type": "build"},
    }


# ═══════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════

class TestFanInWaitManager:
    @pytest.mark.asyncio
    async def test_all_sources_arrive_triggers_merge(self):
        mgr = FanInWaitManager()
        graph = _make_graph(sources=["branch_a", "branch_b"])

        t1 = new_token("test")
        t1["meta"]["fan_out_id"] = "branch_a"
        t1["payload"]["phases"]["research_a"] = {"agent": "lulu", "state": "done"}

        t2 = new_token("test")
        t2["meta"]["fan_out_id"] = "branch_b"
        t2["payload"]["phases"]["research_b"] = {"agent": "thoth", "state": "done"}

        # First arrival — should WAIT
        result1 = await mgr.register_arrival("fan_in", t1, graph)
        assert result1.action == RelayAction.WAIT

        # Second arrival — should ADVANCE with merged token
        result2 = await mgr.register_arrival("fan_in", t2, graph)
        assert result2.action == RelayAction.ADVANCE
        assert result2.next_node == "after_fan_in"
        assert "research_a" in result2.token["payload"]["phases"]
        assert "research_b" in result2.token["payload"]["phases"]

    @pytest.mark.asyncio
    async def test_timeout_fires_callback(self):
        mgr = FanInWaitManager()
        graph = _make_graph(
            sources=["branch_a", "branch_b"],
            timeout_seconds=1,  # fast timeout for test
            on_timeout="route_partial",
        )

        timeout_events = []
        async def on_timeout(fan_in_id, partial, next_node, behavior):
            timeout_events.append({
                "fan_in_id": fan_in_id,
                "partial": partial,
                "next_node": next_node,
                "behavior": behavior,
            })

        mgr.set_callbacks(on_timeout=on_timeout)

        t1 = new_token("test")
        t1["meta"]["fan_out_id"] = "branch_a"
        t1["payload"]["phases"]["research_a"] = {"agent": "lulu", "state": "done"}

        # Register one arrival — should WAIT
        result = await mgr.register_arrival("fan_in", t1, graph)
        assert result.action == RelayAction.WAIT

        # Wait for timeout
        await asyncio.sleep(1.5)

        # Timeout should have fired
        assert len(timeout_events) == 1
        assert timeout_events[0]["fan_in_id"] == "fan_in"
        assert timeout_events[0]["behavior"] == "route_partial"
        assert timeout_events[0]["partial"] is not None
        assert "research_a" in timeout_events[0]["partial"]["payload"]["phases"]

    @pytest.mark.asyncio
    async def test_merge_callback_fires(self):
        mgr = FanInWaitManager()
        graph = _make_graph(sources=["branch_a", "branch_b"])

        merge_events = []
        async def on_merge(fan_in_id, merged, next_node):
            merge_events.append({
                "fan_in_id": fan_in_id,
                "merged": merged,
                "next_node": next_node,
            })

        mgr.set_callbacks(on_merge=on_merge)

        t1 = new_token("test")
        t1["meta"]["fan_out_id"] = "branch_a"
        t2 = new_token("test")
        t2["meta"]["fan_out_id"] = "branch_b"

        await mgr.register_arrival("fan_in", t1, graph)
        await mgr.register_arrival("fan_in", t2, graph)

        assert len(merge_events) == 1
        assert merge_events[0]["fan_in_id"] == "fan_in"
        assert merge_events[0]["next_node"] == "after_fan_in"

    @pytest.mark.asyncio
    async def test_cancel_cleans_up(self):
        mgr = FanInWaitManager()
        graph = _make_graph(sources=["branch_a", "branch_b"])

        t1 = new_token("test")
        t1["meta"]["fan_out_id"] = "branch_a"

        await mgr.register_arrival("fan_in", t1, graph)
        assert await mgr.active_count() == 1

        await mgr.cancel("fan_in")
        assert await mgr.active_count() == 0

    @pytest.mark.asyncio
    async def test_three_branches_all_arrive(self):
        mgr = FanInWaitManager()
        graph = _make_graph(sources=["a", "b", "c"])

        for branch in ["a", "b", "c"]:
            t = new_token("test")
            t["meta"]["fan_out_id"] = branch
            t["payload"]["phases"][f"research_{branch}"] = {"agent": branch, "state": "done"}
            result = await mgr.register_arrival("fan_in", t, graph)
            if branch != "c":
                assert result.action == RelayAction.WAIT
            else:
                assert result.action == RelayAction.ADVANCE
                assert len(result.token["payload"]["phases"]) == 3

    @pytest.mark.asyncio
    async def test_merge_strategy_respected(self):
        mgr = FanInWaitManager()
        graph = _make_graph(sources=["a", "b"], merge_strategy="first")

        t1 = new_token("test")
        t1["meta"]["fan_out_id"] = "a"
        t1["payload"]["phases"]["research_a"] = {"agent": "lulu", "state": "done"}

        t2 = new_token("test")
        t2["meta"]["fan_out_id"] = "b"
        t2["payload"]["phases"]["research_b"] = {"agent": "thoth", "state": "done"}

        await mgr.register_arrival("fan_in", t1, graph)
        result = await mgr.register_arrival("fan_in", t2, graph)

        assert result.action == RelayAction.ADVANCE
        # "first" strategy — only first branch's phases
        assert "research_a" in result.token["payload"]["phases"]
        assert "research_b" not in result.token["payload"]["phases"]

    @pytest.mark.asyncio
    async def test_no_sources_immediate_advance(self):
        mgr = FanInWaitManager()
        graph = _make_graph(sources=[])

        t = new_token("test")
        result = await mgr.register_arrival("fan_in", t, graph)

        # With empty sources, all arrived immediately
        assert result.action == RelayAction.ADVANCE
        assert result.next_node == "after_fan_in"
