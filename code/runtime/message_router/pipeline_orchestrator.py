# pipeline_orchestrator.py
# Wires Gate Engine + Task Lifecycle for the newsletter pipeline.
# Venue-level. Not a nucleus module.

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from gate_engine import GateEngine
from task_lifecycle import TaskLifecycle


PIPELINE_ROOT = Path("~/.maestro/pipelines/newsletter").expanduser()

PHASES = [
    {
        "phase": "research",
        "agent": "lulu",
        "task_prefix": "research",
        "in_gates": None,          # no gates — pipeline start
        "out_gates": "research_out_gates",
        "directive": "Research the top 3 AI agent stories this week. Produce research_output.json with sources, summaries, and angles.",
    },
    {
        "phase": "copy",
        "agent": "penny-lane",
        "task_prefix": "copy",
        "in_gates": "copy_in_gates",
        "out_gates": "copy_out_gates",
        "directive": "Write the newsletter copy based on research_output.json. Produce copy_output.md.",
    },
    {
        "phase": "audit",
        "agent": "mnemosyne",
        "task_prefix": "audit",
        "in_gates": "audit_in_gates",
        "out_gates": "audit_out_gates",
        "directive": "Audit the newsletter copy in copy_output.md. Check facts, tone, and formatting. Produce audit_report.json with approved: true/false and notes.",
    },
    {
        "phase": "build",
        "agent": "proteus",
        "task_prefix": "build",
        "in_gates": "build_in_gates",
        "out_gates": "build_out_gates",
        "directive": "Build the final newsletter from copy_output.md and audit_report.json. Produce final_newsletter.md.",
    },
    {
        "phase": "deliver",
        "agent": "proteus",
        "task_prefix": "deliver",
        "in_gates": "deliver_in_gates",
        "out_gates": None,         # terminal
        "directive": "Deliver final_newsletter.md to Jesse via send_message.",
    },
]


class PipelineOrchestrator:
    """Manages the newsletter pipeline across phases."""

    def __init__(self, task_lifecycle: TaskLifecycle, gate_engine: GateEngine,
                 message_router=None):
        self.tl = task_lifecycle
        self.ge = gate_engine
        self.router = message_router   # for dispatching directives to agents

    def start_pipeline(self, issue_id: str = None) -> dict:
        """Create all tasks for a new pipeline run. Returns {issue_id, tasks}."""
        iid = issue_id or datetime.now().strftime("%Y-%m-%d")
        root = PIPELINE_ROOT / iid
        root.mkdir(parents=True, exist_ok=True)

        tasks = {}
        for phase in PHASES:
            task_id = f"{phase['task_prefix']}-{iid}"
            spec = {
                "pipeline": "newsletter",
                "issue_id": iid,
                "phase": phase["phase"],
                "agent": phase["agent"],
                "directive": phase["directive"],
                "pipeline_root": str(root),
            }
            tid = self.tl.create_task(spec, task_id=task_id)
            tasks[phase["phase"]] = tid

        return {"issue_id": iid, "tasks": tasks, "pipeline_root": str(root)}

    def check_phase_ready(self, phase: dict, issue_id: str) -> dict:
        """Check if a phase's in-gates pass. Returns {ready: bool, reason: str}."""
        if phase["in_gates"] is None:
            return {"ready": True, "reason": "no gates (pipeline start)"}

        gate_method = getattr(self.ge, phase["in_gates"])
        gates = gate_method(issue_id, self.tl)
        decision = self.ge.check_gates(gates)

        return {
            "ready": decision.result.value == "pass",
            "reason": decision.reason,
        }

    def check_phase_complete(self, phase: dict, issue_id: str) -> dict:
        """Check if a phase's out-gates pass. Returns {complete: bool, reason: str}."""
        if phase["out_gates"] is None:
            return {"complete": True, "reason": "no out-gates (terminal)"}

        gate_method = getattr(self.ge, phase["out_gates"])
        gates = gate_method(issue_id)
        decision = self.ge.check_gates(gates)

        return {
            "complete": decision.result.value == "pass",
            "reason": decision.reason,
        }

    def get_pipeline_status(self, issue_id: str) -> dict:
        """Return full pipeline status: each phase's task state + gate status."""
        phases_status = []
        for phase in PHASES:
            task_id = f"{phase['task_prefix']}-{issue_id}"
            task = self.tl.get_state(task_id)
            ready = self.check_phase_ready(phase, issue_id)
            complete = self.check_phase_complete(phase, issue_id)

            phases_status.append({
                "phase": phase["phase"],
                "agent": phase["agent"],
                "task_id": task_id,
                "task_state": task["state"] if task else "not_created",
                "in_gates_pass": ready["ready"],
                "in_gates_reason": ready["reason"],
                "out_gates_pass": complete["complete"],
                "out_gates_reason": complete["reason"],
            })

        return {"issue_id": issue_id, "phases": phases_status}
