"""
audit_log.py — Thread-safe JSONL audit logger with auto-rotation.

Appends JSONL entries to ~/.maestro/audit.jsonl with fcntl-based locking.
Auto-rotates at 100MB, keeping up to 5 backups.
Never raises — all errors are silently caught.
"""

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


# --- Event type constants ---
EVENT_TRANSPORT_RECV = "transport.recv"
EVENT_TRANSPORT_SEND = "transport.send"
EVENT_TOOL_CALL = "tool.call"
EVENT_TOOL_RESULT = "tool.result"
EVENT_EXECUTION_START = "execution.start"
EVENT_EXECUTION_END = "execution.end"
EVENT_CAP_BREACH = "cap.breach"
EVENT_AGENT_START = "agent.start"
EVENT_AGENT_STOP = "agent.stop"
EVENT_KILL = "agent.kill"
EVENT_SESSION_ORPHAN = "session.orphan"
EVENT_DISPATCH_BROADCAST = "dispatch.broadcast"
EVENT_DISPATCH_TARGETED = "dispatch.targeted"
EVENT_DISPATCH_SUPPRESSED = "dispatch.suppressed"
EVENT_SUPERVISOR_KILL = "supervisor.kill"
EVENT_GOVERNED_ORPHAN_CLEANUP = "governed.orphan_cleanup"
EVENT_RETRY_BLOCKED = "retry.blocked"
EVENT_DUPLICATE_SIDE_EFFECT_RETRY_BLOCKED = "duplicate_side_effect_retry_blocked"
EVENT_BROADCAST_BLOCKED_NO_SCOPE = "broadcast_blocked_no_scope"

# --- Config ---
MAX_FILE_BYTES = 100 * 1024 * 1024  # 100 MB
MAX_BACKUPS = 5
DEFAULT_LOG_NAME = "audit.jsonl"


def _log_path() -> Path:
    """Return the primary audit log path."""
    return Path.home() / ".maestro" / DEFAULT_LOG_NAME


def _backup_paths(log_path: Path) -> list[Path]:
    """Return ordered backup paths [1..MAX_BACKUPS], newest first."""
    return [log_path.with_suffix(f".jsonl.{i}") for i in range(1, MAX_BACKUPS + 1)]


def _rotate(log_path: Path) -> None:
    """Rotate log files: remove oldest, shift others up, move primary to .1.

    Caller is responsible for holding the fcntl lock to prevent concurrent rotation.
    """
    try:
        backups = _backup_paths(log_path)

        # Remove the oldest backup if it exists
        if backups[-1].exists():
            backups[-1].unlink()

        # Shift backups: .4 -> .5, .3 -> .4, .1 -> .2
        for i in range(len(backups) - 1, 0, -1):
            if backups[i - 1].exists():
                backups[i - 1].replace(backups[i])

        # Move primary to .1
        if log_path.exists():
            log_path.replace(backups[0])
    except Exception:
        # Never raise — rotation failure is non-fatal
        pass


def write(event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
    """
    Append a JSONL entry to the audit log.

    - Thread-safe via fcntl.flock (POSIX advisory lock).
    - Auto-rotates when the log exceeds 100 MB.
    - Never raises — silently catches all errors.

    Args:
        event_type: A short string identifying the event (e.g. "message_sent").
        data:       Optional dict of arbitrary JSON-serializable data.
    """
    if data is None:
        data = {}

    now = datetime.now(timezone.utc)
    entry = {
        "ts": now.isoformat(),
        "ts_unix": now.timestamp(),
        "event_type": event_type,
        "data": data,
    }

    log_path = _log_path()

    try:
        # Ensure directory exists
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Open in append mode, acquire exclusive lock
        fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)

            # Write the entry
            line = json.dumps(entry, default=str, ensure_ascii=False) + "\n"
            os.write(fd, line.encode("utf-8"))

            # Check rotation while still holding the lock to prevent races
            need_rotate = False
            try:
                st = os.fstat(fd)
                if st.st_size >= MAX_FILE_BYTES:
                    need_rotate = True
            except Exception:
                pass

            # Unlock first — rotation renames the file and we must not hold
            # the fd lock across rename because fcntl locks are tied to
            # (inode, pid) and a rename changes the path but not the inode.
            # Other threads opening the *new* file get a fresh inode/lock.
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            fd = -1  # Mark closed so finally block doesn't double-close

            if need_rotate:
                _rotate(log_path)
        finally:
            if fd != -1:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except Exception:
                    pass
                try:
                    os.close(fd)
                except Exception:
                    pass
    except Exception:
        # Never raise — audit log failures must not propagate
        pass


# --- Convenience ---
if __name__ == "__main__":
    # Quick smoke test
    for i in range(5):
        write("test_event", {"seq": i, "note": f"smoke test {i}"})
    print(f"Wrote 5 test entries to {_log_path()}")
    print(f"File size: {_log_path().stat().st_size} bytes")