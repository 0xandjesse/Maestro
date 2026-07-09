#!/usr/bin/env python3
"""Pipeline Coordinator — ADR-004 Phase 1.

Tails the event bus log, dispatches pipeline phases to agents
when dependency gates clear, and advances the pipeline on completion.

Usage:
    pipeline_coordinator.py [--once] [pipeline_id]

The coordinator is deployment infrastructure — it orchestrates, it doesn't
participate. It has no transport. It reads the event log and writes to the
event bus. Agents never import it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

# ── Paths ────────────────────────────────────────────────────────────────
NUCLEUS_DIR = str(Path.home() / "Projects" / "Maestro" / "nucleus")
# nucleus is installed as editable package in the hermes venv
sys.path.insert(0, str(Path(NUCLEUS_DIR).parent))

from nucleus.modules.gate_engine import InMemoryGateEngine
from nucleus.modules.task_lifecycle import InMemoryTaskLifecycle, TaskState

EVENTS_PATH = Path.home() / ".maestro" / "events" / "events.jsonl"
PIPELINES_DIR = Path.home() / "Projects" / "Maestro" / "nucleus" / "pipelines"
EVENT_BUS_URL = "http://127.0.0.1:8653/maestro/notify"
COORDINATOR_ID = "pipeline-coordinator"
POLL_INTERVAL = 5  # seconds between dispatch checks
RUN_INTERVAL = 300  # seconds between pipeline runs (5 min)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [pipeline] %(message)s",
)
log = logging.getLogger("pipeline")


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline Coordinator
# ═══════════════════════════════════════════════════════════════════════════

class PipelineCoordinator:
    """Orchestrates a single pipeline definition.

    Owns the Gate Engine (dependency enforcement) and Task Lifecycle
    (phase state tracking).  Reads completions from the event log.
    Dispatches work via the event bus.
    """

    def __init__(self, pipeline_def: dict[str, Any]) -> None:
        self.pipeline = pipeline_def
        self.gate_engine = InMemoryGateEngine()
        self.task_lifecycle = InMemoryTaskLifecycle()
        self.active_runs: dict[str, dict[str, Any]] = {}
        # phase_id → task_id mapping for the current run
        self._phase_task_map: dict[str, str] = {}

    # ── Run management ──────────────────────────────────────────────

    def start_run(self) -> str:
        """Create tasks for every phase and wire up dependency gates."""
        pid = self.pipeline["pipeline_id"]
        run_id = f"{pid}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        self._phase_task_map.clear()

        for phase in self.pipeline["phases"]:
            phase_id = phase["phase_id"]
            task = self.task_lifecycle.create_task(
                agent_id=phase["agent"],
                description=phase["description"],
            )
            self._phase_task_map[phase_id] = task.task_id

            # Schedule with a TIME gate (valid immediately)
            self.gate_engine.schedule_token(
                token_id=task.task_id,
                valid_after=int(time.time() * 1000),
            )

        # Wire dependency gates (must happen after all tasks exist)
        for phase in self.pipeline["phases"]:
            task_id = self._phase_task_map[phase["phase_id"]]
            for dep_phase_id in phase.get("depends_on", []):
                dep_task_id = self._phase_task_map.get(dep_phase_id)
                if dep_task_id:
                    self.gate_engine.add_dependency(task_id, dep_task_id)

        self.active_runs[run_id] = {
            "state": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "phase_tasks": dict(self._phase_task_map),
        }

        log.info(f"Run started: {run_id} ({len(self.pipeline['phases'])} phases)")
        return run_id

    # ── Dispatch ─────────────────────────────────────────────────────

    async def dispatch_ready_phases(self, run_id: str) -> list[str]:
        """Send work to every agent whose dependency gates have cleared."""
        dispatched: list[str] = []
        run = self.active_runs.get(run_id)
        if not run:
            return dispatched

        for phase in self.pipeline["phases"]:
            phase_id = phase["phase_id"]
            task_id = run["phase_tasks"].get(phase_id)
            if not task_id:
                continue

            task = self.task_lifecycle.get_task(task_id)
            if not task or task.state != TaskState.PENDING:
                continue

            token = self.gate_engine.get_token(task_id)
            if not token:
                continue

            result = self.gate_engine.check_gates(token)
            if result.name != "PASS":
                continue

            # Gates cleared — claim, then dispatch
            self.task_lifecycle.transition(task_id, TaskState.CLAIMED)
            ok = await self._send_dispatch(phase, task_id, run_id)
            if ok:
                self.task_lifecycle.transition(task_id, TaskState.IN_PROGRESS)
                dispatched.append(phase_id)
            else:
                # Dispatch failed — leave in CLAIMED for retry
                pass

        return dispatched

    async def _send_dispatch(
        self, phase: dict[str, Any], task_id: str, run_id: str
    ) -> bool:
        """POST a work directive to the event bus for *phase*'s agent."""
        payload = {
            "id": str(uuid.uuid4()),
            "msg_type": "direct",
            "from": COORDINATOR_ID,
            "to": phase["agent"],
            "subject": (
                f"[Pipeline] {self.pipeline['pipeline_id']} — "
                f"{phase['phase_id']}"
            ),
            "content": json.dumps({
                "type": "pipeline_dispatch",
                "pipeline_id": self.pipeline["pipeline_id"],
                "phase_id": phase["phase_id"],
                "task_id": task_id,
                "run_id": run_id,
                "description": phase["description"],
                "output_artifact": phase["output_artifact"],
                "timeout_minutes": phase.get("timeout_minutes", 30),
                # The agent should echo these fields in its completion
                "completion_format": {
                    "type": "pipeline_complete",
                    "pipeline_id": self.pipeline["pipeline_id"],
                    "phase_id": phase["phase_id"],
                    "task_id": task_id,
                    "run_id": run_id,
                },
            }),
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    EVENT_BUS_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    body = await resp.text()
                    if resp.status == 200:
                        log.info(
                            "Dispatched %s → %s (task %s)",
                            phase["phase_id"], phase["agent"], task_id[:8],
                        )
                        return True
                    log.error(
                        "Dispatch failed %s: HTTP %s — %s",
                        phase["phase_id"], resp.status, body[:200],
                    )
        except Exception as exc:
            log.error("Dispatch error %s: %s", phase["phase_id"], exc)

        return False

    # ── Completion handling ──────────────────────────────────────────

    def handle_event(self, event: dict[str, Any]) -> str | None:
        """Process an event from the log.  Returns phase_id if completed."""
        content = event.get("content", "")
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return None

        if data.get("type") != "pipeline_complete":
            return None

        phase_id = data.get("phase_id")
        task_id = data.get("task_id")
        status = data.get("status", "done")

        if not phase_id or not task_id:
            return None

        task = self.task_lifecycle.get_task(task_id)
        if not task:
            return None

        if status == "done":
            self.task_lifecycle.transition(task_id, TaskState.DONE)
            self.gate_engine.set_token_state(task_id, "completed")
            artifacts = data.get("artifacts", [])
            summary = data.get("summary", "")
            log.info(
                "Phase complete: %s (task %s, %d artifacts)%s",
                phase_id, task_id[:8], len(artifacts),
                f" — {summary[:80]}" if summary else "",
            )
            return phase_id

        if status == "blocked":
            self.task_lifecycle.transition(task_id, TaskState.BLOCKED)
            log.warning("Phase blocked: %s — %s", phase_id, data.get("summary", ""))
            return None

        return None

    # ── Run status ───────────────────────────────────────────────────

    def is_run_complete(self, run_id: str) -> bool:
        """True when every phase in *run_id* is DONE."""
        run = self.active_runs.get(run_id)
        if not run:
            return False
        return all(
            self._phase_is_done(task_id)
            for task_id in run["phase_tasks"].values()
        )

    def _phase_is_done(self, task_id: str) -> bool:
        task = self.task_lifecycle.get_task(task_id)
        return task is not None and task.state == TaskState.DONE

    def check_timeouts(self, run_id: str) -> list[str]:
        """Mark timed-out phases as BLOCKED.  Returns list of phase_ids."""
        timed_out: list[str] = []
        run = self.active_runs.get(run_id)
        if not run:
            return timed_out

        now_ms = int(time.time() * 1000)
        for phase in self.pipeline["phases"]:
            task_id = run["phase_tasks"].get(phase["phase_id"])
            if not task_id:
                continue
            task = self.task_lifecycle.get_task(task_id)
            if not task or task.state != TaskState.IN_PROGRESS:
                continue
            if task.started_at is None:
                continue

            timeout_ms = phase.get("timeout_minutes", 30) * 60 * 1000
            if (now_ms - task.started_at) > timeout_ms:
                self.task_lifecycle.transition(task_id, TaskState.BLOCKED)
                log.error(
                    "Phase timed out: %s (elapsed %.0f min, limit %d min)",
                    phase["phase_id"],
                    (now_ms - task.started_at) / 60000,
                    phase.get("timeout_minutes", 30),
                )
                timed_out.append(phase["phase_id"])

        return timed_out


# ═══════════════════════════════════════════════════════════════════════════
# Event log tailer
# ═══════════════════════════════════════════════════════════════════════════

async def tail_events(coordinator: PipelineCoordinator) -> None:
    """Tail events.jsonl and feed completions to the coordinator."""
    if not EVENTS_PATH.exists():
        log.error("Events file not found: %s", EVENTS_PATH)
        return

    with open(EVENTS_PATH, "r") as fh:
        fh.seek(0, 2)  # start at end

        while True:
            line = fh.readline()
            if line:
                try:
                    event = json.loads(line)
                    coordinator.handle_event(event)
                except json.JSONDecodeError:
                    pass
            else:
                await asyncio.sleep(0.5)


# ═══════════════════════════════════════════════════════════════════════════
# Main loop
# ═══════════════════════════════════════════════════════════════════════════

async def run_pipeline(pipeline_id: str, *, once: bool = False) -> None:
    """Run a pipeline continuously (or once with --once)."""
    pipeline_path = PIPELINES_DIR / f"{pipeline_id}.json"
    if not pipeline_path.exists():
        log.error("Pipeline definition not found: %s", pipeline_path)
        sys.exit(1)

    with open(pipeline_path) as fh:
        pipeline_def = json.load(fh)

    coordinator = PipelineCoordinator(pipeline_def)
    tailer = asyncio.create_task(tail_events(coordinator))

    run_id: str | None = None
    last_run_end = 0.0

    try:
        while True:
            # Start a new run?
            if run_id is None or coordinator.is_run_complete(run_id):
                if run_id and coordinator.is_run_complete(run_id):
                    coordinator.active_runs[run_id]["state"] = "complete"
                    coordinator.active_runs[run_id]["completed_at"] = (
                        datetime.now(timezone.utc).isoformat()
                    )
                    log.info("Run complete: %s", run_id)
                    last_run_end = time.time()

                    if once:
                        log.info("--once mode: exiting after completed run")
                        break

                # Wait before starting next run
                elapsed = time.time() - last_run_end
                if elapsed < RUN_INTERVAL and last_run_end > 0:
                    wait = RUN_INTERVAL - elapsed
                    log.info("Next run in %.0f seconds", wait)
                    await asyncio.sleep(wait)

                run_id = coordinator.start_run()

            # Dispatch ready phases
            dispatched = await coordinator.dispatch_ready_phases(run_id)
            if dispatched:
                log.info("Dispatched: %s", ", ".join(dispatched))

            # Check timeouts
            timed_out = coordinator.check_timeouts(run_id)
            if timed_out:
                log.warning("Timed out: %s", ", ".join(timed_out))

            await asyncio.sleep(POLL_INTERVAL)

    finally:
        tailer.cancel()
        try:
            await tailer
        except asyncio.CancelledError:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline Coordinator")
    parser.add_argument(
        "pipeline_id", nargs="?", default="newsletter",
        help="Pipeline definition name (default: newsletter)",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run one pipeline cycle and exit",
    )
    args = parser.parse_args()

    log.info("Pipeline Coordinator starting — pipeline=%s", args.pipeline_id)
    asyncio.run(run_pipeline(args.pipeline_id, once=args.once))


if __name__ == "__main__":
    main()
