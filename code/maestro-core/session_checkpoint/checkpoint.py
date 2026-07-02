"""Session Checkpoint — file-backed, atomic-write checkpoint store.

Guarantees
----------
* Atomic writes   — writes land in a temp file, then ``os.rename()``.
* Schema validation — every write is validated; malformed entries are rejected.
* Graceful missing — missing agent directories return None / empty lists.
* Prune keeps last N — oldest checkpoints are deleted first.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .interface import SessionCheckpoint, SessionState
from .schema import validate_state


class FileSessionCheckpoint(SessionCheckpoint):
    """File-backed session checkpoint store.

    Checkpoints are stored as individual JSON files under::

        nucleus/data/checkpoints/{agent_id}/{timestamp}.json

    The timestamp (epoch ms) doubles as the checkpoint_id.
    """

    def __init__(
        self, data_dir: str = "nucleus/data/checkpoints"
    ) -> None:
        self._data_dir = Path(data_dir).resolve()
        self._data_dir.mkdir(parents=True, exist_ok=True)

    # ── public API ─────────────────────────────────────────────────────

    def save(self, agent_id: str, state: SessionState) -> str:
        """Persist *state* and return a checkpoint_id string.

        The checkpoint_id is the epoch-millisecond timestamp used as the
        filename stem.
        """
        if not agent_id:
            raise ValueError("agent_id must be a non-empty string")

        # Ensure agent_id on state matches
        state.agent_id = agent_id
        state.checkpointed_at = int(time.time() * 1000)

        # Validate
        entry = self._state_to_dict(state)
        errors = validate_state(entry)
        if errors:
            raise ValueError(f"schema validation failed: {'; '.join(errors)}")

        # Ensure agent directory exists
        agent_dir = self._data_dir / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Atomic write: temp file → rename
        checkpoint_id = str(state.checkpointed_at)
        target_path = agent_dir / f"{checkpoint_id}.json"
        tmp_path = agent_dir / f"{checkpoint_id}.json.tmp"

        payload = json.dumps(entry, indent=2)

        with open(tmp_path, "w", encoding="utf-8") as tf:
            tf.write(payload)
            tf.flush()
            os.fsync(tf.fileno())

        os.rename(str(tmp_path), str(target_path))

        return checkpoint_id

    def restore(self, agent_id: str) -> SessionState | None:
        """Return the latest checkpoint for *agent_id*, or None."""
        checkpoints = self._list_files(agent_id)
        if not checkpoints:
            return None
        return self._read_checkpoint(agent_id, checkpoints[0])

    def list_checkpoints(self, agent_id: str) -> list[SessionState]:
        """Return all checkpoints for *agent_id*, newest first."""
        checkpoints = self._list_files(agent_id)
        return [
            self._read_checkpoint(agent_id, cid)
            for cid in checkpoints
        ]

    def prune(self, agent_id: str, keep: int = 5) -> int:
        """Keep only the last *keep* checkpoints; return count pruned."""
        if keep < 0:
            raise ValueError(f"keep must be >= 0, got {keep}")

        checkpoints = self._list_files(agent_id)
        if len(checkpoints) <= keep:
            return 0

        to_delete = checkpoints[keep:]  # oldest are at the end
        agent_dir = self._data_dir / agent_id

        pruned = 0
        for cid in to_delete:
            path = agent_dir / f"{cid}.json"
            try:
                path.unlink(missing_ok=True)
                pruned += 1
            except OSError:
                pass

        return pruned

    # ── internal helpers ───────────────────────────────────────────────

    def _agent_dir(self, agent_id: str) -> Path:
        return self._data_dir / agent_id

    def _list_files(self, agent_id: str) -> list[str]:
        """Return checkpoint IDs for *agent_id*, sorted newest first.

        Returns an empty list if the agent directory doesn't exist.
        """
        agent_dir = self._agent_dir(agent_id)
        if not agent_dir.exists() or not agent_dir.is_dir():
            return []

        json_files: list[Path] = []
        for entry in agent_dir.iterdir():
            if entry.is_file() and entry.suffix == ".json" and not entry.name.endswith(".tmp"):
                json_files.append(entry)

        # Sort by stem (timestamp) descending — newest first
        json_files.sort(key=lambda p: p.stem, reverse=True)
        return [p.stem for p in json_files]

    def _read_checkpoint(self, agent_id: str, checkpoint_id: str) -> SessionState:
        """Read a single checkpoint file and return a SessionState."""
        path = self._agent_dir(agent_id) / f"{checkpoint_id}.json"
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return self._dict_to_state(data)

    # ── conversion helpers ─────────────────────────────────────────────

    @staticmethod
    def _state_to_dict(s: SessionState) -> dict[str, Any]:
        return {
            "agent_id": s.agent_id,
            "session_id": s.session_id,
            "active_tasks": list(s.active_tasks),
            "context_summary": s.context_summary,
            "last_message_id": s.last_message_id,
            "checkpointed_at": s.checkpointed_at,
            "version": s.version,
        }

    @staticmethod
    def _dict_to_state(d: dict[str, Any]) -> SessionState:
        return SessionState(
            agent_id=d.get("agent_id", ""),
            session_id=d.get("session_id", ""),
            active_tasks=list(d.get("active_tasks", [])),
            context_summary=d.get("context_summary", ""),
            last_message_id=d.get("last_message_id"),
            checkpointed_at=d.get("checkpointed_at", 0),
            version=d.get("version", 1),
        )
