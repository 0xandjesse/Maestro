# relay_evaluator.py — Modular Relay Evaluator (ADR-006)
# Graph walker for pipeline token routing.
# Pure logic. No I/O. No transport. No policy decisions.
#
# Replaces: pipeline_orchestrator.py (hardcoded PHASES list)
# Replaces: _maybe_advance_pipeline() (linear walker in transport)
#
# Imports gate_engine and task_lifecycle — same pattern as pipeline_orchestrator.

from __future__ import annotations

import copy
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════
# Relay Actions
# ═══════════════════════════════════════════════════════════

class RelayAction(Enum):
    ADVANCE = "advance"       # route token to next node
    WAIT = "wait"             # fan-in waiting for sources
    TERMINAL = "terminal"     # pipeline complete
    BLOCKED = "blocked"       # unrecoverable error
    DISPATCH = "dispatch"     # phase node — dispatch to agent


@dataclass
class RelayResult:
    action: RelayAction
    token: dict
    next_node: str | None = None
    reason: str = ""
    # For DISPATCH: which agent to send to
    agent: str | None = None
    directive: str = ""
    work_type: str = ""


# ═══════════════════════════════════════════════════════════
# Token Helpers
# ═══════════════════════════════════════════════════════════

def new_token(pipeline: str, issue_id: str = None) -> dict:
    """Create a fresh pipeline token."""
    return {
        "token_id": str(uuid.uuid4()),
        "pipeline": pipeline,
        "issue_id": issue_id or "",
        "meta": {
            "current_node": "",
            "loop_iteration": 0,
            "fan_out_id": None,
            "fan_out_parent": None,
            "loop_exhausted": False,
            "sequence_index": 0,
        },
        "payload": {
            "phases": {},
        },
    }


def clone_token(token: dict, fan_out_id: str = None) -> dict:
    """Deep-copy a token. Optionally set fan_out_id on the clone."""
    clone = copy.deepcopy(token)
    clone["token_id"] = str(uuid.uuid4())  # new identity
    if fan_out_id is not None:
        clone["meta"]["fan_out_id"] = fan_out_id
    return clone


def merge_tokens(tokens: list[dict], strategy: str = "append") -> dict:
    """Merge multiple tokens into one. The first token is the base.

    Strategies:
      - append: concatenate all payload.phases entries (default)
      - merge: deep-merge by phase key, last-write-wins
      - first: use first token's phases, discard others
    """
    if not tokens:
        raise ValueError("merge_tokens requires at least one token")
    if len(tokens) == 1:
        return tokens[0]

    base = copy.deepcopy(tokens[0])

    if strategy == "first":
        return base

    if strategy == "append":
        for t in tokens[1:]:
            for key, val in t.get("payload", {}).get("phases", {}).items():
                # If key collision, append with suffix
                if key in base["payload"]["phases"]:
                    suffix = 2
                    while f"{key}_{suffix}" in base["payload"]["phases"]:
                        suffix += 1
                    base["payload"]["phases"][f"{key}_{suffix}"] = val
                else:
                    base["payload"]["phases"][key] = val
        return base

    if strategy == "merge":
        for t in tokens[1:]:
            for key, val in t.get("payload", {}).get("phases", {}).items():
                base["payload"]["phases"][key] = val  # last-write-wins
        return base

    raise ValueError(f"unknown merge strategy: {strategy}")


def accumulate_phase(token: dict, work_type: str, agent: str,
                     state: str, artifact: str = "", summary: str = "") -> dict:
    """Append a phase result to the token's payload.phases."""
    token = copy.deepcopy(token)
    key = work_type
    # If key exists, append with iteration suffix
    if key in token["payload"]["phases"]:
        iteration = token["meta"].get("loop_iteration", 0)
        key = f"{work_type}_iter{iteration}"
    token["payload"]["phases"][key] = {
        "agent": agent,
        "state": state,
        "artifact": artifact,
        "summary": summary,
    }
    return token


# ═══════════════════════════════════════════════════════════
# Condition Evaluator
# ═══════════════════════════════════════════════════════════

def evaluate_condition(condition: dict, token: dict) -> bool:
    """Evaluate a condition against a token.

    condition: {field, operator, value}
    field: dot-notation path into the token (e.g. 'payload.phases.audit.result')
    operator: equals, not_equals, contains, exists, greater_than, less_than
    value: the comparison value

    Returns True if condition matches, False otherwise.
    """
    field = condition.get("field", "")
    operator = condition.get("operator", "equals")
    expected = condition.get("value")

    # Resolve dot-notation field path
    actual = _resolve_field(token, field)

    if operator == "exists":
        return actual is not None

    if actual is None:
        return False

    if operator == "equals":
        return str(actual) == str(expected)
    elif operator == "not_equals":
        return str(actual) != str(expected)
    elif operator == "contains":
        return str(expected) in str(actual)
    elif operator == "greater_than":
        try:
            return float(actual) > float(expected)
        except (ValueError, TypeError):
            return False
    elif operator == "less_than":
        try:
            return float(actual) < float(expected)
        except (ValueError, TypeError):
            return False
    else:
        raise ValueError(f"unknown operator: {operator}")


def _resolve_field(token: dict, field: str) -> Any:
    """Resolve a dot-notation field path against a token dict.
    Returns None if any segment is missing.
    """
    if not field:
        return None
    parts = field.split(".")
    current = token
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


# ═══════════════════════════════════════════════════════════
# Node Evaluators
# ═══════════════════════════════════════════════════════════

def _eval_sequence(token: dict, graph: dict, node: dict,
                   current_node: str) -> RelayResult:
    """Sequence: route through an ordered list of node IDs."""
    nodes = node.get("nodes", [])
    if not nodes:
        return RelayResult(RelayAction.TERMINAL, token,
                          reason="empty sequence")

    # Find current position — use token's current_node (tracks actual position)
    # Fall back to the sequence node ID if token hasn't been through this sequence yet
    tracked = token["meta"].get("current_node", "")
    seq_index = token["meta"].get("sequence_index", 0)
    try:
        pos = nodes.index(tracked)
        seq_index = pos
    except ValueError:
        # tracked node is the sequence node itself (first entry) — start at -1
        seq_index = -1

    if seq_index >= len(nodes) - 1:
        return RelayResult(RelayAction.TERMINAL, token,
                          reason="sequence complete")

    next_node = nodes[seq_index + 1]
    token["meta"]["sequence_index"] = seq_index + 1
    token["meta"]["current_node"] = next_node
    return RelayResult(RelayAction.ADVANCE, token, next_node=next_node,
                      reason=f"sequence: {current_node} → {next_node}")


def _eval_branch(token: dict, graph: dict, node: dict) -> RelayResult:
    """Branch: evaluate condition, route to matching target."""
    condition = node.get("condition", {})
    routes = node.get("routes", [])
    on_match = node.get("on_match")
    on_mismatch = node.get("on_mismatch")
    fallback = node.get("fallback")

    result = evaluate_condition(condition, token)

    # Multi-way branch
    if routes:
        for route in routes:
            route_val = route.get("value")
            if str(route_val) == str(_resolve_field(token, condition.get("field", ""))):
                target = route.get("target")
                if target:
                    token["meta"]["current_node"] = target
                    return RelayResult(RelayAction.ADVANCE, token,
                                      next_node=target,
                                      reason=f"branch matched route: {route_val}")
        # No route matched
        if fallback:
            token["meta"]["current_node"] = fallback
            return RelayResult(RelayAction.ADVANCE, token,
                              next_node=fallback,
                              reason="branch: no route matched, using fallback")
        return RelayResult(RelayAction.BLOCKED, token,
                          reason="branch: no route matched, no fallback")

    # 2-way branch
    if result:
        if on_match:
            token["meta"]["current_node"] = on_match
            return RelayResult(RelayAction.ADVANCE, token,
                              next_node=on_match,
                              reason="branch: condition matched")
        return RelayResult(RelayAction.TERMINAL, token,
                          reason="branch: matched, no on_match target")
    else:
        if on_mismatch:
            token["meta"]["current_node"] = on_mismatch
            return RelayResult(RelayAction.ADVANCE, token,
                              next_node=on_mismatch,
                              reason="branch: condition did not match")
        if fallback:
            token["meta"]["current_node"] = fallback
            return RelayResult(RelayAction.ADVANCE, token,
                              next_node=fallback,
                              reason="branch: no match, using fallback")
        return RelayResult(RelayAction.BLOCKED, token,
                          reason="branch: no match, no mismatch target, no fallback")


def _eval_fan_out(token: dict, graph: dict, node: dict) -> RelayResult:
    """Fan-out: clone token for each target, route clones.
    Returns a special result with clones list for the transport to dispatch.
    """
    targets = node.get("targets", [])
    if not targets:
        # No targets — route to next if defined
        next_node = node.get("next")
        if next_node:
            token["meta"]["current_node"] = next_node
            return RelayResult(RelayAction.ADVANCE, token,
                              next_node=next_node,
                              reason="fan_out: empty targets, routing to next")
        return RelayResult(RelayAction.TERMINAL, token,
                          reason="fan_out: empty targets, no next")

    clones = []
    for target in targets:
        target_node = target.get("node")
        clone = clone_token(token, fan_out_id=target_node)
        clone["meta"]["fan_out_parent"] = token["meta"].get("current_node", "")
        clone["meta"]["current_node"] = target_node
        clones.append(clone)

    # Return the first clone as the primary result, with clones list attached
    # The transport iterates clones and dispatches each
    primary = clones[0] if clones else token
    primary["_fan_out_clones"] = clones  # transport reads this
    return RelayResult(RelayAction.ADVANCE, primary,
                      next_node=targets[0].get("node"),
                      reason=f"fan_out: {len(clones)} clones")


def _eval_fan_in(token: dict, graph: dict, node: dict) -> RelayResult:
    """Fan-in: wait for all source branches to complete.
    Returns WAIT if not all sources have arrived.
    The transport's FanInWaitManager handles the actual waiting.
    """
    sources = node.get("sources", [])
    if not sources:
        # No sources to wait for — route to next
        next_node = node.get("next")
        if next_node:
            token["meta"]["current_node"] = next_node
            return RelayResult(RelayAction.ADVANCE, token,
                              next_node=next_node,
                              reason="fan_in: no sources, routing to next")
        return RelayResult(RelayAction.TERMINAL, token,
                          reason="fan_in: no sources, no next")

    # The evaluator can't know if all sources have arrived — that's the
    # FanInWaitManager's job. Return WAIT and let the transport handle it.
    return RelayResult(RelayAction.WAIT, token,
                      reason=f"fan_in: waiting for {len(sources)} sources")


def _eval_loop(token: dict, graph: dict, node: dict) -> RelayResult:
    """Loop: evaluate exit condition, re-enter body or exit."""
    max_iterations = node.get("max_iterations")
    if max_iterations is None:
        return RelayResult(RelayAction.BLOCKED, token,
                          reason="loop: max_iterations is required")

    condition = node.get("condition", {})
    body = node.get("body", [])
    after = node.get("after")
    on_max = node.get("on_max", "route_with_warning")
    fallback = node.get("fallback")

    # Initialize loop iteration
    loop_iter = token["meta"].get("loop_iteration", 0)

    # Check exit condition
    if evaluate_condition(condition, token):
        # Condition met — exit loop
        if after:
            token["meta"]["current_node"] = after
            return RelayResult(RelayAction.ADVANCE, token,
                              next_node=after,
                              reason=f"loop: condition met after {loop_iter} iterations")
        return RelayResult(RelayAction.TERMINAL, token,
                          reason=f"loop: condition met, no after target")

    # Condition not met — check max iterations
    if loop_iter >= max_iterations:
        token["meta"]["loop_exhausted"] = True
        if on_max == "route_with_warning":
            if after:
                token["meta"]["current_node"] = after
                return RelayResult(RelayAction.ADVANCE, token,
                                  next_node=after,
                                  reason=f"loop: max iterations ({max_iterations}) reached, routing with warning")
            return RelayResult(RelayAction.TERMINAL, token,
                              reason=f"loop: max iterations reached, no after target")
        elif on_max == "fail":
            return RelayResult(RelayAction.BLOCKED, token,
                              reason=f"loop: max iterations ({max_iterations}) reached, failing")
        elif on_max == "route_to_fallback":
            if fallback:
                token["meta"]["current_node"] = fallback
                return RelayResult(RelayAction.ADVANCE, token,
                                  next_node=fallback,
                                  reason=f"loop: max iterations reached, routing to fallback")
            return RelayResult(RelayAction.BLOCKED, token,
                              reason="loop: max iterations reached, no fallback configured")

    # Re-enter loop body
    if not body:
        return RelayResult(RelayAction.BLOCKED, token,
                          reason="loop: empty body")

    token["meta"]["loop_iteration"] = loop_iter + 1
    token["meta"]["current_node"] = body[0]
    return RelayResult(RelayAction.ADVANCE, token,
                      next_node=body[0],
                      reason=f"loop: iteration {loop_iter + 1}/{max_iterations}")


def _eval_phase(token: dict, graph: dict, node: dict) -> RelayResult:
    """Phase: dispatch work to an agent. This is the only node that invokes an LLM."""
    agent = node.get("agent")
    if not agent:
        return RelayResult(RelayAction.BLOCKED, token,
                          reason="phase: no agent specified")

    work_type = node.get("work_type", "work")
    directive = node.get("directive", "")
    next_node = node.get("next")

    # In-gates are evaluated by the transport before dispatch.
    # The evaluator just returns DISPATCH — the transport handles gate checks.

    return RelayResult(RelayAction.DISPATCH, token,
                      next_node=next_node,
                      agent=agent,
                      directive=directive,
                      work_type=work_type,
                      reason=f"phase: dispatch to {agent} ({work_type})")


# ═══════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════

def evaluate(token: dict, graph: dict, current_node: str) -> RelayResult:
    """Evaluate one node in the relay graph. Pure function.

    Args:
        token: The accumulated pipeline token
        graph: The full workflow graph (dict of node_id -> node)
        current_node: The node ID to evaluate

    Returns:
        RelayResult with action and modified token
    """
    node = graph.get(current_node)
    if not node:
        return RelayResult(RelayAction.BLOCKED, token,
                          reason=f"node not found: {current_node}")

    node_type = node.get("type")

    if node_type == "sequence":
        return _eval_sequence(token, graph, node, current_node)
    elif node_type == "branch":
        return _eval_branch(token, graph, node)
    elif node_type == "fan_out":
        return _eval_fan_out(token, graph, node)
    elif node_type == "fan_in":
        return _eval_fan_in(token, graph, node)
    elif node_type == "loop":
        return _eval_loop(token, graph, node)
    elif node_type == "phase":
        return _eval_phase(token, graph, node)
    else:
        return RelayResult(RelayAction.BLOCKED, token,
                          reason=f"unknown node type: {node_type}")
