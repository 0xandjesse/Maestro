# test_relay_evaluator.py — Unit tests for relay_evaluator.py
# Tests all 6 node types + condition evaluator + token helpers + edge cases.

import sys
import pytest
from pathlib import Path

# Ensure the message_router directory is on the path
sys.path.insert(0, str(Path(__file__).parent))

from relay_evaluator import (
    RelayAction, RelayResult,
    new_token, clone_token, merge_tokens, accumulate_phase,
    evaluate_condition, evaluate,
)


# ═══════════════════════════════════════════════════════════
# Token Helpers
# ═══════════════════════════════════════════════════════════

class TestNewToken:
    def test_creates_fresh_token(self):
        t = new_token("newsletter", "2026-07-04")
        assert t["pipeline"] == "newsletter"
        assert t["issue_id"] == "2026-07-04"
        assert t["token_id"] != ""
        assert t["meta"]["current_node"] == ""
        assert t["meta"]["loop_iteration"] == 0
        assert t["payload"]["phases"] == {}

    def test_unique_token_ids(self):
        t1 = new_token("test")
        t2 = new_token("test")
        assert t1["token_id"] != t2["token_id"]


class TestCloneToken:
    def test_deep_copy_independent(self):
        t = new_token("test")
        t["payload"]["phases"]["research"] = {"agent": "lulu", "state": "done"}
        clone = clone_token(t, fan_out_id="branch_a")
        # Modify clone
        clone["payload"]["phases"]["research"]["state"] = "modified"
        # Original unchanged
        assert t["payload"]["phases"]["research"]["state"] == "done"

    def test_sets_fan_out_id(self):
        t = new_token("test")
        clone = clone_token(t, fan_out_id="branch_a")
        assert clone["meta"]["fan_out_id"] == "branch_a"

    def test_new_token_id(self):
        t = new_token("test")
        clone = clone_token(t)
        assert clone["token_id"] != t["token_id"]


class TestMergeTokens:
    def test_append_strategy(self):
        t1 = new_token("test")
        t1["payload"]["phases"]["research"] = {"agent": "lulu", "state": "done"}
        t2 = new_token("test")
        t2["payload"]["phases"]["copy"] = {"agent": "penny-lane", "state": "done"}
        merged = merge_tokens([t1, t2], strategy="append")
        assert "research" in merged["payload"]["phases"]
        assert "copy" in merged["payload"]["phases"]

    def test_append_key_collision(self):
        t1 = new_token("test")
        t1["payload"]["phases"]["research"] = {"agent": "lulu", "state": "done"}
        t2 = new_token("test")
        t2["payload"]["phases"]["research"] = {"agent": "thoth", "state": "done"}
        merged = merge_tokens([t1, t2], strategy="append")
        # Both should be present — second gets suffix
        assert "research" in merged["payload"]["phases"]
        assert "research_2" in merged["payload"]["phases"]

    def test_merge_strategy_last_write_wins(self):
        t1 = new_token("test")
        t1["payload"]["phases"]["research"] = {"agent": "lulu", "state": "done"}
        t2 = new_token("test")
        t2["payload"]["phases"]["research"] = {"agent": "thoth", "state": "done"}
        merged = merge_tokens([t1, t2], strategy="merge")
        assert merged["payload"]["phases"]["research"]["agent"] == "thoth"

    def test_first_strategy(self):
        t1 = new_token("test")
        t1["payload"]["phases"]["research"] = {"agent": "lulu", "state": "done"}
        t2 = new_token("test")
        t2["payload"]["phases"]["copy"] = {"agent": "penny-lane", "state": "done"}
        merged = merge_tokens([t1, t2], strategy="first")
        assert "research" in merged["payload"]["phases"]
        assert "copy" not in merged["payload"]["phases"]

    def test_single_token(self):
        t = new_token("test")
        merged = merge_tokens([t])
        assert merged["token_id"] == t["token_id"]

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            merge_tokens([])


class TestAccumulatePhase:
    def test_adds_phase_entry(self):
        t = new_token("test")
        t = accumulate_phase(t, "research", "lulu", "done",
                            artifact="out.json", summary="done")
        assert t["payload"]["phases"]["research"]["agent"] == "lulu"
        assert t["payload"]["phases"]["research"]["state"] == "done"
        assert t["payload"]["phases"]["research"]["artifact"] == "out.json"

    def test_key_collision_with_iteration(self):
        t = new_token("test")
        t["meta"]["loop_iteration"] = 2
        t = accumulate_phase(t, "audit", "mnemosyne", "done")
        t = accumulate_phase(t, "audit", "mnemosyne", "done")
        assert "audit" in t["payload"]["phases"]
        assert "audit_iter2" in t["payload"]["phases"]


# ═══════════════════════════════════════════════════════════
# Condition Evaluator
# ═══════════════════════════════════════════════════════════

class TestEvaluateCondition:
    def test_equals_match(self):
        t = {"payload": {"phases": {"audit": {"result": "pass"}}}}
        assert evaluate_condition(
            {"field": "payload.phases.audit.result", "operator": "equals", "value": "pass"}, t)

    def test_equals_no_match(self):
        t = {"payload": {"phases": {"audit": {"result": "fail"}}}}
        assert not evaluate_condition(
            {"field": "payload.phases.audit.result", "operator": "equals", "value": "pass"}, t)

    def test_not_equals(self):
        t = {"payload": {"phases": {"audit": {"result": "fail"}}}}
        assert evaluate_condition(
            {"field": "payload.phases.audit.result", "operator": "not_equals", "value": "pass"}, t)

    def test_contains(self):
        t = {"payload": {"text": "hello world"}}
        assert evaluate_condition(
            {"field": "payload.text", "operator": "contains", "value": "world"}, t)

    def test_contains_no_match(self):
        t = {"payload": {"text": "hello world"}}
        assert not evaluate_condition(
            {"field": "payload.text", "operator": "contains", "value": "xyz"}, t)

    def test_exists_true(self):
        t = {"payload": {"phases": {"audit": {"result": "pass"}}}}
        assert evaluate_condition(
            {"field": "payload.phases.audit.result", "operator": "exists"}, t)

    def test_exists_false(self):
        t = {"payload": {"phases": {}}}
        assert not evaluate_condition(
            {"field": "payload.phases.audit.result", "operator": "exists"}, t)

    def test_greater_than(self):
        t = {"meta": {"loop_iteration": 5}}
        assert evaluate_condition(
            {"field": "meta.loop_iteration", "operator": "greater_than", "value": 3}, t)

    def test_greater_than_false(self):
        t = {"meta": {"loop_iteration": 2}}
        assert not evaluate_condition(
            {"field": "meta.loop_iteration", "operator": "greater_than", "value": 3}, t)

    def test_less_than(self):
        t = {"meta": {"loop_iteration": 2}}
        assert evaluate_condition(
            {"field": "meta.loop_iteration", "operator": "less_than", "value": 5}, t)

    def test_missing_field_returns_false(self):
        t = {"payload": {}}
        assert not evaluate_condition(
            {"field": "payload.nonexistent.key", "operator": "equals", "value": "x"}, t)

    def test_none_actual_returns_false(self):
        t = {"payload": {"val": None}}
        assert not evaluate_condition(
            {"field": "payload.val", "operator": "equals", "value": "x"}, t)


# ═══════════════════════════════════════════════════════════
# Sequence Node
# ═══════════════════════════════════════════════════════════

class TestSequence:
    def test_routes_a_to_b(self):
        graph = {
            "seq": {"type": "sequence", "nodes": ["a", "b", "c"]},
            "a": {"type": "phase", "agent": "lulu", "work_type": "research"},
            "b": {"type": "phase", "agent": "penny-lane", "work_type": "copy"},
            "c": {"type": "phase", "agent": "mnemosyne", "work_type": "audit"},
        }
        t = new_token("test")
        t["meta"]["current_node"] = "seq"
        # First call: seq → a (first node)
        result = evaluate(t, graph, "seq")
        assert result.action == RelayAction.ADVANCE
        assert result.next_node == "a"
        assert t["meta"]["sequence_index"] == 0
        # Second call: a → b
        t["meta"]["current_node"] = "a"
        result = evaluate(t, graph, "seq")
        assert result.action == RelayAction.ADVANCE
        assert result.next_node == "b"

    def test_terminal_at_end(self):
        graph = {
            "seq": {"type": "sequence", "nodes": ["a", "b"]},
            "a": {"type": "phase", "agent": "lulu", "work_type": "research"},
            "b": {"type": "phase", "agent": "penny-lane", "work_type": "copy"},
        }
        t = new_token("test")
        t["meta"]["current_node"] = "b"  # at last node
        result = evaluate(t, graph, "seq")
        assert result.action == RelayAction.TERMINAL

    def test_empty_sequence(self):
        graph = {"seq": {"type": "sequence", "nodes": []}}
        t = new_token("test")
        t["meta"]["current_node"] = "seq"
        result = evaluate(t, graph, "seq")
        assert result.action == RelayAction.TERMINAL


# ═══════════════════════════════════════════════════════════
# Branch Node
# ═══════════════════════════════════════════════════════════

class TestBranch:
    def test_two_way_match(self):
        graph = {
            "branch": {
                "type": "branch",
                "condition": {"field": "payload.phases.audit.result", "operator": "equals", "value": "pass"},
                "on_match": "publish",
                "on_mismatch": "revise",
            },
            "publish": {"type": "phase", "agent": "proteus", "work_type": "publish"},
            "revise": {"type": "phase", "agent": "penny-lane", "work_type": "revise"},
        }
        t = new_token("test")
        t["payload"]["phases"]["audit"] = {"result": "pass"}
        t["meta"]["current_node"] = "branch"
        result = evaluate(t, graph, "branch")
        assert result.action == RelayAction.ADVANCE
        assert result.next_node == "publish"

    def test_two_way_mismatch(self):
        graph = {
            "branch": {
                "type": "branch",
                "condition": {"field": "payload.phases.audit.result", "operator": "equals", "value": "pass"},
                "on_match": "publish",
                "on_mismatch": "revise",
            },
            "publish": {"type": "phase", "agent": "proteus", "work_type": "publish"},
            "revise": {"type": "phase", "agent": "penny-lane", "work_type": "revise"},
        }
        t = new_token("test")
        t["payload"]["phases"]["audit"] = {"result": "fail"}
        t["meta"]["current_node"] = "branch"
        result = evaluate(t, graph, "branch")
        assert result.action == RelayAction.ADVANCE
        assert result.next_node == "revise"

    def test_multi_way_switch(self):
        graph = {
            "branch": {
                "type": "branch",
                "condition": {"field": "payload.tier", "operator": "equals", "value": "premium"},
                "routes": [
                    {"value": "premium", "target": "premium_flow"},
                    {"value": "basic", "target": "basic_flow"},
                ],
                "fallback": "default_flow",
            },
            "premium_flow": {"type": "phase", "agent": "lulu", "work_type": "premium"},
            "basic_flow": {"type": "phase", "agent": "thoth", "work_type": "basic"},
            "default_flow": {"type": "phase", "agent": "penny-lane", "work_type": "default"},
        }
        t = new_token("test")
        t["payload"]["tier"] = "premium"
        t["meta"]["current_node"] = "branch"
        result = evaluate(t, graph, "branch")
        assert result.action == RelayAction.ADVANCE
        assert result.next_node == "premium_flow"

    def test_fallback_when_no_match(self):
        graph = {
            "branch": {
                "type": "branch",
                "condition": {"field": "payload.tier", "operator": "equals", "value": "premium"},
                "routes": [
                    {"value": "premium", "target": "premium_flow"},
                ],
                "fallback": "default_flow",
            },
            "premium_flow": {"type": "phase", "agent": "lulu", "work_type": "premium"},
            "default_flow": {"type": "phase", "agent": "penny-lane", "work_type": "default"},
        }
        t = new_token("test")
        t["payload"]["tier"] = "enterprise"
        t["meta"]["current_node"] = "branch"
        result = evaluate(t, graph, "branch")
        assert result.action == RelayAction.ADVANCE
        assert result.next_node == "default_flow"

    def test_blocked_no_match_no_fallback(self):
        graph = {
            "branch": {
                "type": "branch",
                "condition": {"field": "payload.tier", "operator": "equals", "value": "premium"},
                "routes": [{"value": "premium", "target": "premium_flow"}],
            },
            "premium_flow": {"type": "phase", "agent": "lulu", "work_type": "premium"},
        }
        t = new_token("test")
        t["payload"]["tier"] = "enterprise"
        t["meta"]["current_node"] = "branch"
        result = evaluate(t, graph, "branch")
        assert result.action == RelayAction.BLOCKED


# ═══════════════════════════════════════════════════════════
# Fan-Out Node
# ═══════════════════════════════════════════════════════════

class TestFanOut:
    def test_produces_clones(self):
        graph = {
            "fan": {
                "type": "fan_out",
                "targets": [
                    {"node": "research_lulu", "agent": "lulu"},
                    {"node": "research_thoth", "agent": "thoth"},
                ],
            },
            "research_lulu": {"type": "phase", "agent": "lulu", "work_type": "research"},
            "research_thoth": {"type": "phase", "agent": "thoth", "work_type": "research"},
        }
        t = new_token("test")
        t["meta"]["current_node"] = "fan"
        result = evaluate(t, graph, "fan")
        assert result.action == RelayAction.ADVANCE
        assert "_fan_out_clones" in result.token
        assert len(result.token["_fan_out_clones"]) == 2
        # Each clone has unique token_id
        ids = [c["token_id"] for c in result.token["_fan_out_clones"]]
        assert len(set(ids)) == 2
        # Each clone has fan_out_id set
        fan_ids = [c["meta"]["fan_out_id"] for c in result.token["_fan_out_clones"]]
        assert "research_lulu" in fan_ids
        assert "research_thoth" in fan_ids

    def test_empty_targets_with_next(self):
        graph = {
            "fan": {"type": "fan_out", "targets": [], "next": "after_fan"},
            "after_fan": {"type": "phase", "agent": "proteus", "work_type": "build"},
        }
        t = new_token("test")
        t["meta"]["current_node"] = "fan"
        result = evaluate(t, graph, "fan")
        assert result.action == RelayAction.ADVANCE
        assert result.next_node == "after_fan"

    def test_empty_targets_no_next(self):
        graph = {"fan": {"type": "fan_out", "targets": []}}
        t = new_token("test")
        t["meta"]["current_node"] = "fan"
        result = evaluate(t, graph, "fan")
        assert result.action == RelayAction.TERMINAL


# ═══════════════════════════════════════════════════════════
# Fan-In Node
# ═══════════════════════════════════════════════════════════

class TestFanIn:
    def test_returns_wait(self):
        graph = {
            "fin": {
                "type": "fan_in",
                "sources": ["research_lulu", "research_thoth"],
                "merge_strategy": "append",
                "next": "copy",
            },
            "copy": {"type": "phase", "agent": "penny-lane", "work_type": "copy"},
        }
        t = new_token("test")
        t["meta"]["current_node"] = "fin"
        result = evaluate(t, graph, "fin")
        assert result.action == RelayAction.WAIT

    def test_no_sources_routes_to_next(self):
        graph = {
            "fin": {"type": "fan_in", "sources": [], "next": "copy"},
            "copy": {"type": "phase", "agent": "penny-lane", "work_type": "copy"},
        }
        t = new_token("test")
        t["meta"]["current_node"] = "fin"
        result = evaluate(t, graph, "fin")
        assert result.action == RelayAction.ADVANCE
        assert result.next_node == "copy"


# ═══════════════════════════════════════════════════════════
# Loop Node
# ═══════════════════════════════════════════════════════════

class TestLoop:
    def test_exits_when_condition_met(self):
        graph = {
            "loop": {
                "type": "loop",
                "max_iterations": 3,
                "condition": {"field": "payload.phases.audit.result", "operator": "equals", "value": "pass"},
                "body": ["audit"],
                "after": "publish",
            },
            "audit": {"type": "phase", "agent": "mnemosyne", "work_type": "audit"},
            "publish": {"type": "phase", "agent": "proteus", "work_type": "publish"},
        }
        t = new_token("test")
        t["payload"]["phases"]["audit"] = {"result": "pass"}
        t["meta"]["current_node"] = "loop"
        result = evaluate(t, graph, "loop")
        assert result.action == RelayAction.ADVANCE
        assert result.next_node == "publish"

    def test_reenters_body_when_condition_not_met(self):
        graph = {
            "loop": {
                "type": "loop",
                "max_iterations": 3,
                "condition": {"field": "payload.phases.audit.result", "operator": "equals", "value": "pass"},
                "body": ["audit"],
                "after": "publish",
            },
            "audit": {"type": "phase", "agent": "mnemosyne", "work_type": "audit"},
            "publish": {"type": "phase", "agent": "proteus", "work_type": "publish"},
        }
        t = new_token("test")
        t["payload"]["phases"]["audit"] = {"result": "fail"}
        t["meta"]["current_node"] = "loop"
        result = evaluate(t, graph, "loop")
        assert result.action == RelayAction.ADVANCE
        assert result.next_node == "audit"
        assert t["meta"]["loop_iteration"] == 1

    def test_max_iterations_route_with_warning(self):
        graph = {
            "loop": {
                "type": "loop",
                "max_iterations": 2,
                "condition": {"field": "payload.phases.audit.result", "operator": "equals", "value": "pass"},
                "body": ["audit"],
                "after": "publish",
                "on_max": "route_with_warning",
            },
            "audit": {"type": "phase", "agent": "mnemosyne", "work_type": "audit"},
            "publish": {"type": "phase", "agent": "proteus", "work_type": "publish"},
        }
        t = new_token("test")
        t["payload"]["phases"]["audit"] = {"result": "fail"}
        t["meta"]["loop_iteration"] = 2  # already at max
        t["meta"]["current_node"] = "loop"
        result = evaluate(t, graph, "loop")
        assert result.action == RelayAction.ADVANCE
        assert result.next_node == "publish"
        assert t["meta"]["loop_exhausted"] is True

    def test_max_iterations_fail(self):
        graph = {
            "loop": {
                "type": "loop",
                "max_iterations": 2,
                "condition": {"field": "payload.phases.audit.result", "operator": "equals", "value": "pass"},
                "body": ["audit"],
                "after": "publish",
                "on_max": "fail",
            },
            "audit": {"type": "phase", "agent": "mnemosyne", "work_type": "audit"},
            "publish": {"type": "phase", "agent": "proteus", "work_type": "publish"},
        }
        t = new_token("test")
        t["payload"]["phases"]["audit"] = {"result": "fail"}
        t["meta"]["loop_iteration"] = 2
        t["meta"]["current_node"] = "loop"
        result = evaluate(t, graph, "loop")
        assert result.action == RelayAction.BLOCKED

    def test_max_iterations_route_to_fallback(self):
        graph = {
            "loop": {
                "type": "loop",
                "max_iterations": 2,
                "condition": {"field": "payload.phases.audit.result", "operator": "equals", "value": "pass"},
                "body": ["audit"],
                "after": "publish",
                "on_max": "route_to_fallback",
                "fallback": "manual_review",
            },
            "audit": {"type": "phase", "agent": "mnemosyne", "work_type": "audit"},
            "publish": {"type": "phase", "agent": "proteus", "work_type": "publish"},
            "manual_review": {"type": "phase", "agent": "lexicon", "work_type": "review"},
        }
        t = new_token("test")
        t["payload"]["phases"]["audit"] = {"result": "fail"}
        t["meta"]["loop_iteration"] = 2
        t["meta"]["current_node"] = "loop"
        result = evaluate(t, graph, "loop")
        assert result.action == RelayAction.ADVANCE
        assert result.next_node == "manual_review"

    def test_missing_max_iterations(self):
        graph = {
            "loop": {
                "type": "loop",
                "condition": {"field": "x", "operator": "equals", "value": "y"},
                "body": ["audit"],
            },
            "audit": {"type": "phase", "agent": "mnemosyne", "work_type": "audit"},
        }
        t = new_token("test")
        t["meta"]["current_node"] = "loop"
        result = evaluate(t, graph, "loop")
        assert result.action == RelayAction.BLOCKED

    def test_empty_body(self):
        graph = {
            "loop": {
                "type": "loop",
                "max_iterations": 3,
                "condition": {"field": "x", "operator": "equals", "value": "y"},
                "body": [],
            },
        }
        t = new_token("test")
        t["meta"]["current_node"] = "loop"
        result = evaluate(t, graph, "loop")
        assert result.action == RelayAction.BLOCKED


# ═══════════════════════════════════════════════════════════
# Phase Node
# ═══════════════════════════════════════════════════════════

class TestPhase:
    def test_dispatches_to_agent(self):
        graph = {
            "research": {
                "type": "phase",
                "agent": "lulu",
                "work_type": "research",
                "directive": "Research top stories",
                "next": "copy",
            },
            "copy": {"type": "phase", "agent": "penny-lane", "work_type": "copy"},
        }
        t = new_token("test")
        t["meta"]["current_node"] = "research"
        result = evaluate(t, graph, "research")
        assert result.action == RelayAction.DISPATCH
        assert result.agent == "lulu"
        assert result.work_type == "research"
        assert result.directive == "Research top stories"
        assert result.next_node == "copy"

    def test_missing_agent(self):
        graph = {"bad": {"type": "phase", "work_type": "test"}}
        t = new_token("test")
        t["meta"]["current_node"] = "bad"
        result = evaluate(t, graph, "bad")
        assert result.action == RelayAction.BLOCKED


# ═══════════════════════════════════════════════════════════
# Main evaluate() — Edge Cases
# ═══════════════════════════════════════════════════════════

class TestEvaluate:
    def test_node_not_found(self):
        graph = {}
        t = new_token("test")
        result = evaluate(t, graph, "nonexistent")
        assert result.action == RelayAction.BLOCKED

    def test_unknown_node_type(self):
        graph = {"weird": {"type": "quantum_entanglement"}}
        t = new_token("test")
        t["meta"]["current_node"] = "weird"
        result = evaluate(t, graph, "weird")
        assert result.action == RelayAction.BLOCKED


# ═══════════════════════════════════════════════════════════
# Integration: Full Pipeline Graph
# ═══════════════════════════════════════════════════════════

class TestFullPipeline:
    """Test a complete newsletter pipeline graph:
    start → research(fan_out: lulu, thoth) → fan_in → copy → audit(loop) → publish
    """

    def _make_graph(self):
        return {
            "start": {
                "type": "sequence",
                "nodes": ["fan_out_research", "fan_in_research", "copy", "audit_loop", "publish"],
            },
            "fan_out_research": {
                "type": "fan_out",
                "targets": [
                    {"node": "research_lulu", "agent": "lulu"},
                    {"node": "research_thoth", "agent": "thoth"},
                ],
            },
            "research_lulu": {
                "type": "phase", "agent": "lulu", "work_type": "research_lulu",
                "directive": "Research from Lulu's angle", "next": "fan_in_research",
            },
            "research_thoth": {
                "type": "phase", "agent": "thoth", "work_type": "research_thoth",
                "directive": "Research from Thoth's angle", "next": "fan_in_research",
            },
            "fan_in_research": {
                "type": "fan_in",
                "sources": ["research_lulu", "research_thoth"],
                "merge_strategy": "append",
                "next": "copy",
            },
            "copy": {
                "type": "phase", "agent": "penny-lane", "work_type": "copy",
                "directive": "Write copy", "next": "audit_loop",
            },
            "audit_loop": {
                "type": "loop",
                "max_iterations": 3,
                "condition": {"field": "payload.phases.audit.result", "operator": "equals", "value": "pass"},
                "body": ["audit"],
                "after": "publish",
            },
            "audit": {
                "type": "phase", "agent": "mnemosyne", "work_type": "audit",
                "directive": "Audit the copy", "next": "audit_loop",
            },
            "publish": {
                "type": "phase", "agent": "proteus", "work_type": "publish",
                "directive": "Publish newsletter",
            },
        }

    def test_start_routes_to_fan_out(self):
        graph = self._make_graph()
        t = new_token("newsletter", "2026-07-04")
        t["meta"]["current_node"] = "start"
        result = evaluate(t, graph, "start")
        assert result.action == RelayAction.ADVANCE
        assert result.next_node == "fan_out_research"

    def test_fan_out_produces_two_clones(self):
        graph = self._make_graph()
        t = new_token("newsletter", "2026-07-04")
        t["meta"]["current_node"] = "fan_out_research"
        result = evaluate(t, graph, "fan_out_research")
        assert "_fan_out_clones" in result.token
        assert len(result.token["_fan_out_clones"]) == 2

    def test_audit_loop_exits_on_pass(self):
        graph = self._make_graph()
        t = new_token("newsletter", "2026-07-04")
        t["payload"]["phases"]["audit"] = {"result": "pass"}
        t["meta"]["current_node"] = "audit_loop"
        result = evaluate(t, graph, "audit_loop")
        assert result.action == RelayAction.ADVANCE
        assert result.next_node == "publish"

    def test_audit_loop_reenters_on_fail(self):
        graph = self._make_graph()
        t = new_token("newsletter", "2026-07-04")
        t["payload"]["phases"]["audit"] = {"result": "fail"}
        t["meta"]["current_node"] = "audit_loop"
        result = evaluate(t, graph, "audit_loop")
        assert result.action == RelayAction.ADVANCE
        assert result.next_node == "audit"
        assert t["meta"]["loop_iteration"] == 1
