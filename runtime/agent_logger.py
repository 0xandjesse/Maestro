"""Structured agent action logger for Maestro transport.

Schema per line (JSON):
{
    ts:       int   # epoch milliseconds
    agent_id: str
    action:   str
    params:   dict
    result:   dict | None
    session_id: str
}
"""
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional


MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


class AgentLogger:
    def __init__(self, log_dir: str = "", lock: Optional[threading.Lock] = None):
        self.log_dir = Path(log_dir) if log_dir else Path.home() / ".maestro" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = lock or threading.Lock()

    def _log_path(self, agent_id: str) -> Path:
        return self.log_dir / f"{agent_id}.jsonl"

    def _rotate_if_needed(self, agent_id: str) -> None:
        path = self._log_path(agent_id)
        if path.exists() and path.stat().st_size >= MAX_FILE_SIZE:
            rotated = self.log_dir / f"{agent_id}.jsonl.1"
            if rotated.exists():
                rotated.unlink()
            path.rename(rotated)

    def log(self, agent_id: str, action: str, params: Dict[str, Any],
            result: Optional[Dict[str, Any]] = None, session_id: str = "") -> None:
        entry = {
            "ts": int(time.time() * 1000),
            "agent_id": agent_id,
            "action": action,
            "params": params if params is not None else {},
            "result": result,
            "session_id": session_id,
        }
        with self._lock:
            try:
                self._rotate_if_needed(agent_id)
                path = self._log_path(agent_id)
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                # Never crash the caller because of logging issues.
                pass
