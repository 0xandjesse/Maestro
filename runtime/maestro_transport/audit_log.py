"""
Audit log for Maestro transport.

Appends one JSONL line per event to ~/.maestro/audit.jsonl with:
  - Thread-safe writes via fcntl.flock (inter-process safe)
  - Auto-rotation at 100 MB, keeping up to 5 backups (.1 through .5)
  - Never raises — all I/O errors are silently swallowed

Schema per line:
  {
    "ts":          "2026-05-18T04:06:00.123Z",   # ISO 8601 UTC
    "event_type":  "task_start",                  # caller-defined event category
    "data":        { ... }                        # arbitrary JSON-serialisable payload
  }

Usage:
    from audit_log import write

    write("task_start", {"task_id": "abc", "agent": "proteus"})
    write("message_sent", {"recipient": "stormtrooper", "payload_size": 2048})
"""

import fcntl
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
AUDIT_PATH = Path(os.getenv("MAESTRO_AUDIT_PATH", os.path.expanduser("~/.maestro/audit.jsonl")))
MAX_FILE_BYTES = 100 * 1024 * 1024   # 100 MB
MAX_BACKUPS = 5                        # keep .1 … .5

# Module-level lock serialises threads *within* one process.
_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Event type constants (Tactical Hardening Phase 1, Priority 4)
# ---------------------------------------------------------------------------
EVENT_AGENT_START = "agent.start"
EVENT_AGENT_STOP = "agent.stop"
EVENT_EXECUTION_START = "execution.start"
EVENT_EXECUTION_END = "execution.end"
EVENT_TOOL_CALL = "tool.call"
EVENT_TOOL_RESULT = "tool.result"
EVENT_KILL = "kill"
EVENT_CAP_BREACH = "cap.breach"
EVENT_TRANSPORT_SEND = "transport.send"
EVENT_TRANSPORT_RECV = "transport.recv"
EVENT_ERROR = "error"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_dir(path: Path) -> None:
    """Create parent directories if they don't exist."""
    path.parent.mkdir(parents=True, exist_ok=True)


def _rotate(path: Path) -> None:
    """
    Rotate the audit log when it exceeds MAX_FILE_BYTES.

    Keeps up to MAX_BACKUPS compressed-history files:
        audit.jsonl      -> audit.jsonl.1
        audit.jsonl.1    -> audit.jsonl.2
        ...
        audit.jsonl.5    -> deleted (if it exists)
    """
    try:
        if not path.exists():
            return
        if path.stat().st_size < MAX_FILE_BYTES:
            return
    except OSError:
        return

    # Delete the oldest backup (.5) to make room, then shift: .4->.5, .3->.4, .2->.3, .1->.2
    oldest = path.parent / f"{path.name}.{MAX_BACKUPS}"
    try:
        if oldest.exists():
            oldest.unlink()
    except OSError:
        pass

    for i in range(MAX_BACKUPS - 1, 0, -1):
        src = path.parent / f"{path.name}.{i}"
        dst = path.parent / f"{path.name}.{i + 1}"
        try:
            if src.exists():
                src.rename(dst)
        except OSError:
            pass

    # Main file -> .1
    backup_1 = path.parent / f"{path.name}.1"
    try:
        if backup_1.exists():
            backup_1.unlink()
        path.rename(backup_1)
    except OSError:
        pass


def _serialise(data: Any) -> Any:
    """
    Make *data* safe for json.dumps.
    Falls back to str() for non-serialisable types so the log line
    is always written even if the caller passes a weird object.
    """
    try:
        json.dumps(data, ensure_ascii=False)
        return data
    except (TypeError, ValueError):
        return str(data)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write(event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
    """
    Append an audit event to the JSONL log.

    Parameters
    ----------
    event_type : str
        Category / name of the event (e.g. "task_start", "message_sent").
    data : dict, optional
        Arbitrary payload.  Keys are strings; values must be JSON-serialisable.
        Non-serialisable values are coerced to strings.

    Guarantees
    ----------
    * Thread-safe (threading.Lock + fcntl.flock).
    * Never raises — all I/O errors are silently swallowed so the caller
      never crashes because of audit logging.
    * Auto-rotates the log file at 100 MB, keeping up to 5 backups.
    """
    entry = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event_type": event_type,
        "data": _serialise(data) if data is not None else {},
    }

    line: str
    try:
        line = json.dumps(entry, ensure_ascii=False) + "\n"
    except (TypeError, ValueError):
        # Last resort: minimal log line so we never lose the event entirely.
        line = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "event_type": str(event_type),
            "data": {},
        }, ensure_ascii=False) + "\n"

    with _lock:
        try:
            _ensure_dir(AUDIT_PATH)
            _rotate(AUDIT_PATH)

            # Append with fcntl file-lock for inter-process safety.
            with open(AUDIT_PATH, "a", encoding="utf-8") as f:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            # Never propagate — audit logging must not crash the caller.
            pass


# ---------------------------------------------------------------------------
# Convenience: module-level __all__
# ---------------------------------------------------------------------------
__all__ = [
    "write",
    "EVENT_AGENT_START",
    "EVENT_AGENT_STOP",
    "EVENT_EXECUTION_START",
    "EVENT_EXECUTION_END",
    "EVENT_TOOL_CALL",
    "EVENT_TOOL_RESULT",
    "EVENT_KILL",
    "EVENT_CAP_BREACH",
    "EVENT_TRANSPORT_SEND",
    "EVENT_TRANSPORT_RECV",
    "EVENT_ERROR",
]