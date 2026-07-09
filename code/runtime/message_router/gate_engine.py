# gate_engine.py — Gate Engine (M03)
# Evaluates dependency gates for pipeline transitions.
# Pure logic. No I/O. No transport. No policy decisions.

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Callable
import json
import time


class GateResult(Enum):
    PASS = "pass"
    BLOCK = "block"


@dataclass
class GateDecision:
    result: GateResult
    reason: str = ""          # human-readable reason on block
    checked_at: int = field(default_factory=lambda: int(time.time() * 1000))


# ── Gate types ──────────────────────────────────────────

@dataclass
class ArtifactGate:
    """Require a file to exist, be non-empty, and optionally pass a validator."""
    path: str
    validator: Optional[Callable] = None

    def check(self) -> GateDecision:
        p = Path(self.path)
        if not p.exists():
            return GateDecision(GateResult.BLOCK, f"artifact missing: {self.path}")
        if p.stat().st_size == 0:
            return GateDecision(GateResult.BLOCK, f"artifact empty: {self.path}")
        if self.validator:
            return self.validator(p)
        return GateDecision(GateResult.PASS)


@dataclass
class DependencyGate:
    """Require a task to be in a specific state."""
    task_id: str
    required_state: str          # "done", "in_progress", etc.
    task_lifecycle: object        # TaskLifecycle instance (duck-typed)

    def check(self) -> GateDecision:
        state = self.task_lifecycle.get_state(self.task_id)
        if state is None:
            return GateDecision(GateResult.BLOCK, f"task not found: {self.task_id}")
        current = state.get("state", "unknown")
        if current != self.required_state:
            return GateDecision(GateResult.BLOCK,
                f"task {self.task_id} is '{current}', need '{self.required_state}'")
        return GateDecision(GateResult.PASS)


@dataclass
class TimeGate:
    """Require current time >= a Unix timestamp."""
    not_before: int              # Unix timestamp (seconds)

    def check(self) -> GateDecision:
        if time.time() < self.not_before:
            return GateDecision(GateResult.BLOCK,
                f"too early: {time.time()} < {self.not_before}")
        return GateDecision(GateResult.PASS)


# ── Gate Engine ──────────────────────────────────────────

class GateEngine:
    """Evaluate a list of gates. All must PASS for the transition to proceed."""

    def check_gates(self, gates: list) -> GateDecision:
        """Evaluate all gates in order. Returns first BLOCK or PASS if all pass."""
        for i, gate in enumerate(gates):
            decision = gate.check()
            if decision.result == GateResult.BLOCK:
                decision.reason = f"gate[{i}] {type(gate).__name__}: {decision.reason}"
                return decision
        return GateDecision(GateResult.PASS)

    # Convenience: named gate sets for the newsletter pipeline

    @staticmethod
    def research_out_gates(issue_id: str, pipeline_root: str = "~/.maestro/pipelines/newsletter") -> list:
        root = Path(pipeline_root).expanduser() / issue_id
        return [
            ArtifactGate(str(root / "research_output.json"),
                validator=GateEngine._validate_json_nonempty),
        ]

    @staticmethod
    def copy_in_gates(issue_id: str, task_lifecycle, pipeline_root: str = "~/.maestro/pipelines/newsletter") -> list:
        root = Path(pipeline_root).expanduser() / issue_id
        return [
            DependencyGate(f"research-{issue_id}", "done", task_lifecycle),
            ArtifactGate(str(root / "research_output.json")),
        ]

    @staticmethod
    def copy_out_gates(issue_id: str, pipeline_root: str = "~/.maestro/pipelines/newsletter") -> list:
        root = Path(pipeline_root).expanduser() / issue_id
        return [
            ArtifactGate(str(root / "copy_output.md")),
        ]

    @staticmethod
    def audit_in_gates(issue_id: str, task_lifecycle, pipeline_root: str = "~/.maestro/pipelines/newsletter") -> list:
        root = Path(pipeline_root).expanduser() / issue_id
        return [
            DependencyGate(f"copy-{issue_id}", "done", task_lifecycle),
            ArtifactGate(str(root / "copy_output.md")),
        ]

    @staticmethod
    def audit_out_gates(issue_id: str, pipeline_root: str = "~/.maestro/pipelines/newsletter") -> list:
        root = Path(pipeline_root).expanduser() / issue_id
        return [
            ArtifactGate(str(root / "audit_report.json"),
                validator=GateEngine._validate_audit_approved),
        ]

    @staticmethod
    def build_in_gates(issue_id: str, task_lifecycle, pipeline_root: str = "~/.maestro/pipelines/newsletter") -> list:
        root = Path(pipeline_root).expanduser() / issue_id
        return [
            DependencyGate(f"audit-{issue_id}", "done", task_lifecycle),
            ArtifactGate(str(root / "audit_report.json"),
                validator=GateEngine._validate_audit_approved),
        ]

    @staticmethod
    def build_out_gates(issue_id: str, pipeline_root: str = "~/.maestro/pipelines/newsletter") -> list:
        root = Path(pipeline_root).expanduser() / issue_id
        return [
            ArtifactGate(str(root / "final_newsletter.md")),
        ]

    @staticmethod
    def deliver_in_gates(issue_id: str, task_lifecycle, pipeline_root: str = "~/.maestro/pipelines/newsletter") -> list:
        root = Path(pipeline_root).expanduser() / issue_id
        return [
            DependencyGate(f"build-{issue_id}", "done", task_lifecycle),
            ArtifactGate(str(root / "final_newsletter.md")),
        ]

    # ── Validators ───────────────────────────────────────

    @staticmethod
    def _validate_json_nonempty(path: Path) -> GateDecision:
        try:
            data = json.loads(path.read_text())
            if not data:
                return GateDecision(GateResult.BLOCK, f"JSON file is empty object: {path}")
            return GateDecision(GateResult.PASS)
        except json.JSONDecodeError as e:
            return GateDecision(GateResult.BLOCK, f"invalid JSON: {e}")

    @staticmethod
    def _validate_audit_approved(path: Path) -> GateDecision:
        try:
            data = json.loads(path.read_text())
            if not data.get("approved", False):
                return GateDecision(GateResult.BLOCK, f"audit not approved: {path}")
            return GateDecision(GateResult.PASS)
        except json.JSONDecodeError as e:
            return GateDecision(GateResult.BLOCK, f"invalid JSON: {e}")
