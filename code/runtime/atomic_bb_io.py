#!/usr/bin/env python3
"""
Atomic blackboard I/O utility.

Provides locked_read / locked_write and a context-manager for
read-modify-write cycles on JSON-backed blackboards.
All operations use fcntl advisory locking to prevent inter-process corruption.
"""

import fcntl
import json
import os
import tempfile
from pathlib import Path
from contextlib import contextmanager


def _open_locked(path: Path, write: bool = False):
    """Open path with advisory lock. Returns (fd, path). Caller must close fd."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT
    fd = os.open(str(path), flags)
    lock_type = fcntl.LOCK_EX if write else fcntl.LOCK_SH
    fcntl.flock(fd, lock_type)
    return fd


def _read_fd(fd) -> any:
    """Read JSON from an open fd. Returns dict/list or {} on error."""
    try:
        size = os.lseek(fd, 0, os.SEEK_END)
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, size).decode("utf-8") if size else ""
        if not raw.strip():
            return {}
        data = json.loads(raw)
        return data if isinstance(data, (dict, list)) else {}
    except Exception:
        return {}


def _write_fd(fd, data):
    """Overwrite fd atomically (via truncate + write + fsync)."""
    payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, payload)
    os.fsync(fd)
    return len(payload)


@contextmanager
def atomic_board(path: Path, default=dict):
    """Context manager for atomic read-modify-write on a JSON board.

    Usage:
        with atomic_board(board_path) as data:
            data["key"] = "value"
    """
    path = Path(path)
    fd = _open_locked(path, write=True)
    try:
        data = _read_fd(fd)
        if not isinstance(data, (dict, list)) or (isinstance(data, dict) and default != dict):
            data = default()
        yield data
        _write_fd(fd, data)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def safe_read(path: Path, default=dict):
    """Read a JSON file with shared lock. Returns default() on missing/corrupt."""
    path = Path(path)
    if not path.exists():
        return default()
    fd = None
    try:
        fd = _open_locked(path, write=False)
        return _read_fd(fd)
    except Exception:
        return default()
    finally:
        if fd is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def safe_write(path: Path, data) -> dict:
    """Write JSON with exclusive lock. Returns {ok, bytes} or {ok: False, error}."""
    fd = None
    try:
        fd = _open_locked(path, write=True)
        _write_fd(fd, data)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        if fd is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
