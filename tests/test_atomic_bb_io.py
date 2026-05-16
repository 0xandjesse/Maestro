"""test_atomic_bb_io.py — atomic blackboard I/O tests."""

import json
import os
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from atomic_bb_io import safe_read, safe_write, atomic_board


def test_safe_read_missing_returns_default():
    with TemporaryDirectory() as tmpdir:
        missing = Path(tmpdir) / "nope.json"
        assert safe_read(missing) == {}
        assert safe_read(missing, default=list) == []


def test_safe_write_and_read_roundtrip():
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "bb.json"
        assert safe_write(path, {"key": "val"})["ok"]
        assert safe_read(path) == {"key": "val"}


def test_atomic_board_read_modify_write():
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "board.json"
        with atomic_board(path) as data:
            data["a"] = 1
            data["b"] = [2, 3]
        with atomic_board(path) as data:
            data["a"] = 42
        assert safe_read(path) == {"a": 42, "b": [2, 3]}


def test_atomic_board_isolation():
    """Two RMW cycles in sequence should never see partial writes."""
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "counters.json"
        safe_write(path, {"count": 0})
        for _ in range(100):
            with atomic_board(path) as data:
                data["count"] += 1
        result = safe_read(path)
        assert result["count"] == 100


def test_corrupt_file_returns_default():
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "bad.json"
        path.write_text("not json{{[")
        assert safe_read(path) == {}


def test_concurrent_safe_writes():
    """Stress advisory locking: many threads doing safe_write interleave correctly."""
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "concurrent.json"
        errors = []
        safe_write(path, [])

        def append_worker():
            for i in range(50):
                try:
                    with atomic_board(path, default=list) as data:
                        data.append(i)
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=append_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        data = safe_read(path, default=list)
        assert len(data) == 200
        assert not errors


def test_atomic_board_list_default():
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "listboard.json"
        # When file is missing, atomic_board uses list default
        with atomic_board(path, default=list) as data:
            data.append(1)
        assert safe_read(path, default=list) == [1]
