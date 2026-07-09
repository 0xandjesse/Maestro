# pipeline_runner.py — Tokenized Pipeline Runner
# Wires relay_evaluator + gate_engine + task_lifecycle for graph-based pipelines.
# Replaces: pipeline_orchestrator.py (hardcoded PHASES list)
# Replaces: _maybe_advance_pipeline() (linear walker in transport)
#
# The transport calls on_directive_complete() when an agent finishes work.
# The runner advances the token through the graph, dispatching next phases.

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from relay_evaluator import (
    RelayAction, RelayResult, evaluate, new_token, accumulate_phase, clone_token
)
from gate_engine import GateEngine, ArtifactGate, DependencyGate, GateDecision, GateResult
from task_lifecycle import TaskLifecycle

log = logging.getLogger(__name__)

PIPELINES_ROOT = Path("~/.maestro/pipelines").expanduser()


class PipelineRunner:
    """Manages tokenized pipeline execution using the relay evaluator."""

    def __init__(
        self,
        registry,                # LocalRegistry — for agent endpoint lookup
        task_lifecycle: TaskLifecycle,
        gate_engine: GateEngine,
        deliver_callback: Callable,  # async def deliver(endpoint, directive)
        agent_id: str = "proteus",
    ):
        self.registry = registry
        self.tl = task_lifecycle
        self.ge = gate_engine
        self._deliver = deliver_callback
        self.agent_id = agent_id

    # ── Public API ──────────────────────────────────────────

    async def start_pipeline(
        self, pipeline_name: str, issue_id: str = None, adr_ref: str = None
    ) -> dict:
        """Create a new pipeline run. Dispatches the first phase.

        Returns {issue_id, pipeline_root, first_task_id}.
        """
        iid = issue_id or datetime.now().strftime("%Y-%m-%d")
        root = PIPELINES_ROOT / pipeline_name / iid
        root.mkdir(parents=True, exist_ok=True)

        # Load graph
        graph_path = PIPELINES_ROOT / pipeline_name / "graph.json"
        if not graph_path.exists():
            return {"ok": False, "reason": f"graph not found: {graph_path}"}
        graph = json.loads(graph_path.read_text())

        # Create token
        token = new_token(pipeline_name, iid)
        token["meta"]["pipeline_root"] = str(root)
        if adr_ref:
            token["meta"]["adr_ref"] = adr_ref

        start_node_id = graph.get("start", list(graph["nodes"].keys())[0])
        token["meta"]["current_node"] = start_node_id
        self._save_token(root, token)

        # Dispatch first phase
        start_node = graph["nodes"].get(start_node_id)
        if not start_node or start_node.get("type") != "phase":
            return {"ok": False, "reason": f"start node {start_node_id} is not a phase"}

        task_id = await self._dispatch_phase(token, graph, start_node, root, iid)
        if not task_id:
            return {"ok": False, "reason": "failed to dispatch first phase"}

        log.info(f"Pipeline {pipeline_name}/{iid} started — first phase: {start_node_id} → {start_node.get('agent')}")
        return {
            "ok": True,
            "issue_id": iid,
            "pipeline_root": str(root),
            "first_task_id": task_id,
            "first_agent": start_node.get("agent"),
        }

    async def on_directive_complete(self, message: dict) -> Optional[dict]:
        """Called by the transport when a directive finishes.

        Finds the pipeline context, marks the phase complete, checks out-gates,
        and advances to the next node.

        Returns the next dispatch result if a new phase was dispatched, or None.
        """
        # Extract task context
        content = message.get("content", "")
        task_id = self._extract_task_id(content)
        if not task_id:
            return None

        task = self.tl.get_state(task_id)
        if not task:
            return None

        spec = task.get("spec", {})
        pipeline_name = spec.get("pipeline")
        issue_id = spec.get("issue_id")
        if not pipeline_name or not issue_id:
            return None

        root = Path(spec.get("pipeline_root", str(PIPELINES_ROOT / pipeline_name / issue_id)))

        # Load graph and token
        graph_path = PIPELINES_ROOT / pipeline_name / "graph.json"
        if not graph_path.exists():
            log.warning(f"Pipeline graph not found: {graph_path}")
            return None
        graph = json.loads(graph_path.read_text())

        token = self._load_token(root)
        if not token:
            log.warning(f"Token not found for {pipeline_name}/{issue_id}")
            return None

        # Find which node this task belongs to
        current_node_id = spec.get("node_id")
        if not current_node_id:
            return None

        current_node = graph["nodes"].get(current_node_id)
        if not current_node:
            return None

        # Check out-gates
        out_gates = self._build_gates(current_node.get("out_gates", []), root, issue_id)
        if out_gates:
            decision = self.ge.check_gates(out_gates)
            if decision.result == GateResult.BLOCK:
                log.info(f"Pipeline {pipeline_name}/{issue_id}: {current_node_id} out-gates blocked — {decision.reason}")
                return None

        # Mark phase complete in token
        token = accumulate_phase(
            token,
            work_type=current_node.get("work_type", "work"),
            agent=current_node.get("agent", "unknown"),
            state="done",
            summary=f"Task {task_id} completed",
        )
        self._save_token(root, token)

        # Advance
        return await self._advance(token, graph, root, issue_id, pipeline_name)

    # ── Internal: Graph Walking ────────────────────────────

    async def _advance(
        self, token: dict, graph: dict, root: Path, issue_id: str, pipeline_name: str
    ) -> Optional[dict]:
        """Call evaluate() and handle the result. Recursive for ADVANCE actions."""
        current_node_id = token["meta"].get("current_node", "")
        result = evaluate(token, graph, current_node_id)

        if result.action == RelayAction.TERMINAL:
            log.info(f"Pipeline {pipeline_name}/{issue_id} complete — {result.reason}")
            token["meta"]["pipeline_state"] = "complete"
            self._save_token(root, token)
            return {"action": "terminal", "reason": result.reason}

        elif result.action == RelayAction.BLOCKED:
            log.error(f"Pipeline {pipeline_name}/{issue_id} blocked — {result.reason}")
            token["meta"]["pipeline_state"] = "blocked"
            self._save_token(root, token)
            return {"action": "blocked", "reason": result.reason}

        elif result.action == RelayAction.WAIT:
            log.info(f"Pipeline {pipeline_name}/{issue_id}: waiting for fan-in — {result.reason}")
            token["meta"]["pipeline_state"] = "waiting"
            self._save_token(root, token)
            return {"action": "wait", "reason": result.reason}

        elif result.action == RelayAction.ADVANCE:
            # Update token and recurse
            token = result.token
            token["meta"]["current_node"] = result.next_node
            self._save_token(root, token)

            next_node = graph["nodes"].get(result.next_node)
            if not next_node:
                log.error(f"Node not found: {result.next_node}")
                return None

            if next_node["type"] == "phase":
                task_id = await self._dispatch_phase(token, graph, next_node, root, issue_id)
                if task_id:
                    return {"action": "dispatched", "node": result.next_node, "task_id": task_id, "agent": next_node.get("agent")}
                return None

            elif next_node["type"] == "fan_out":
                return await self._handle_fan_out(token, graph, next_node, root, issue_id, pipeline_name)

            elif next_node["type"] == "fan_in":
                # Fan-in: the evaluator returns WAIT. The transport's FanInWaitManager handles it.
                # Just recurse — the evaluator will return WAIT or ADVANCE.
                return await self._advance(token, graph, root, issue_id, pipeline_name)

            elif next_node["type"] in ("sequence", "branch", "loop"):
                # Structural nodes — recurse
                return await self._advance(token, graph, root, issue_id, pipeline_name)

            else:
                log.warning(f"Unknown node type: {next_node['type']}")
                return None

        elif result.action == RelayAction.DISPATCH:
            # Direct dispatch (shouldn't normally happen in _advance, but handle it)
            next_node = graph["nodes"].get(result.next_node or current_node_id)
            if next_node and next_node["type"] == "phase":
                task_id = await self._dispatch_phase(token, graph, next_node, root, issue_id)
                if task_id:
                    return {"action": "dispatched", "node": result.next_node, "task_id": task_id, "agent": next_node.get("agent")}
            return None

        return None

    async def _handle_fan_out(
        self, token: dict, graph: dict, node: dict, root: Path, issue_id: str, pipeline_name: str
    ) -> Optional[dict]:
        """Fan-out: dispatch to all target nodes in parallel."""
        targets = node.get("targets", [])
        if not targets:
            return await self._advance(token, graph, root, issue_id, pipeline_name)

        dispatched = []
        for target in targets:
            target_node_id = target.get("node")
            target_node = graph["nodes"].get(target_node_id)
            if not target_node or target_node["type"] != "phase":
                continue

            # Clone token for each branch
            branch_token = clone_token(token, fan_out_id=target_node_id)
            branch_token["meta"]["current_node"] = target_node_id
            branch_token["meta"]["fan_out_parent"] = token["meta"].get("current_node", "")

            # Save branch token
            branch_root = root / f"branch_{target_node_id}"
            branch_root.mkdir(parents=True, exist_ok=True)
            self._save_token(branch_root, branch_token)

            task_id = await self._dispatch_phase(branch_token, graph, target_node, branch_root, issue_id)
            if task_id:
                dispatched.append({"node": target_node_id, "task_id": task_id, "agent": target_node.get("agent")})

        log.info(f"Pipeline {pipeline_name}/{issue_id}: fan-out dispatched {len(dispatched)} branches")
        return {"action": "fan_out", "dispatched": dispatched}

    # ── Internal: Dispatch ──────────────────────────────────

    async def _dispatch_phase(
        self, token: dict, graph: dict, node: dict, root: Path, issue_id: str
    ) -> Optional[str]:
        """Send directive to agent, create task, return task_id."""
        agent_id = node.get("agent")
        if not agent_id:
            log.error("Phase node has no agent")
            return None

        # Check in-gates
        in_gates = self._build_gates(node.get("in_gates", []), root, issue_id)
        if in_gates:
            decision = self.ge.check_gates(in_gates)
            if decision.result == GateResult.BLOCK:
                log.info(f"In-gates blocked for {node.get('work_type')}: {decision.reason}")
                return None

        # Look up agent endpoint
        agent_reg = self.registry.lookup(agent_id)
        if not agent_reg:
            log.warning(f"Agent {agent_id} not in registry")
            return None

        endpoint = agent_reg.get("webhookEndpoint")
        if not endpoint:
            log.warning(f"No endpoint for {agent_id}")
            return None

        # Find the node_id in the graph
        node_id = None
        for nid, n in graph["nodes"].items():
            if n is node:
                node_id = nid
                break

        # Create task
        directive_text = node.get("directive", "").replace("{pipeline_root}", str(root))
        task_spec = {
            "pipeline": token.get("pipeline", ""),
            "issue_id": issue_id,
            "node_id": node_id,
            "phase": node.get("work_type", "work"),
            "agent": agent_id,
            "directive": directive_text,
            "pipeline_root": str(root),
        }
        task_id = self.tl.create_task(task_spec)

        # Build directive message
        directive_msg = {
            "id": str(uuid.uuid4()),
            "type": "directive",
            "sender": {"agentId": self.agent_id},
            "recipient": {"agentId": agent_id},
            "content": (
                f"Subject: Pipeline {token.get('pipeline')}/{issue_id} — {node.get('work_type', 'work')}\n\n"
                f"{directive_text}\n\n"
                f"Task ID: {task_id}\n"
                f"Pipeline root: {root}"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Claim and dispatch
        self.tl.claim_task(agent_id, task_id)
        self.tl.start_work(agent_id, task_id)

        await self._deliver(endpoint, directive_msg)
        log.info(f"Dispatched {node.get('work_type')} to {agent_id} (task {task_id})")
        return task_id

    # ── Internal: Gates ─────────────────────────────────────

    def _build_gates(self, gate_specs: list, root: Path, issue_id: str) -> list:
        """Convert gate specs from the graph into GateEngine gate objects."""
        gates = []
        for spec in gate_specs:
            gate_type = spec.get("type")
            if gate_type == "artifact":
                path = spec["path"].replace("{pipeline_root}", str(root))
                gates.append(ArtifactGate(path))
            elif gate_type == "dependency":
                task_id = spec["task_id"].replace("{issue_id}", issue_id)
                gates.append(DependencyGate(task_id, spec.get("required_state", "done"), self.tl))
        return gates

    # ── Internal: Token Persistence ────────────────────────

    def _token_path(self, root: Path) -> Path:
        return root / "token.json"

    def _load_token(self, root: Path) -> Optional[dict]:
        p = self._token_path(root)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except Exception:
            return None

    def _save_token(self, root: Path, token: dict):
        self._token_path(root).write_text(json.dumps(token, indent=2, ensure_ascii=False))

    # ── Internal: Helpers ──────────────────────────────────

    def _extract_task_id(self, content: str) -> Optional[str]:
        """Extract task_id from directive content."""
        if not content:
            return None
        for line in content.splitlines():
            if line.strip().startswith("Task ID:"):
                return line.split(":", 1)[1].strip()
        return None
