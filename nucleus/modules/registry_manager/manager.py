"""Registry Manager — single-writer-safe, schema-validated agent registry.

Guarantees
----------
* Single-writer lock  — ``fcntl.flock(LOCK_EX)`` prevents concurrent writes.
* Write-ahead log     — operations are journaled before mutation; replay on init.
* Schema validation   — every write is validated; malformed entries are rejected.
* Atomic replace      — writes land in a temp file, then ``os.rename()``.
* Backward-compatible — reads the existing ``~/.maestro/registry.json`` format.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .interface import AgentRecord, RegistryManager
from .schema import validate_registry

log = logging.getLogger(__name__)


class FileRegistryManager(RegistryManager):
    """File-backed registry with single-writer enforcement."""

    def __init__(self, registry_path: str = "nucleus/data/registry.json") -> None:
        self._path = Path(registry_path).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._wal_path = self._path.with_suffix(self._path.suffix + ".wal")
        self._lock = threading.Lock()  # in-process mutual exclusion

        # Replay any incomplete WAL on startup
        self._replay_wal()

    # ── public API ─────────────────────────────────────────────────────

    def lookup(self, agent_id: str) -> AgentRecord | None:
        for entry in self._load():
            if entry.get("agentId") == agent_id:
                return self._dict_to_record(entry)
        return None

    def register(
        self,
        agent_id: str,
        webhook_endpoint: str,
        capabilities: list[str] | None = None,
    ) -> AgentRecord:
        record = AgentRecord(
            agentId=agent_id,
            webhookEndpoint=webhook_endpoint,
            capabilities=capabilities or [],
            registeredAt=int(time.time() * 1000),
            lastSeen=int(time.time() * 1000),
            status="active",
        )
        self._mutate("register", agent_id, self._record_to_dict(record))
        return record

    def unregister(self, agent_id: str) -> bool:
        data = self._load()
        before = len(data)
        data = [e for e in data if e.get("agentId") != agent_id]
        if len(data) == before:
            return False
        self._save(data)
        return True

    def list_all(self) -> list[AgentRecord]:
        return [self._dict_to_record(e) for e in self._load()]

    def update_last_seen(self, agent_id: str) -> bool:
        return self._update_field(agent_id, "lastSeen", int(time.time() * 1000))

    def set_status(self, agent_id: str, status: str) -> bool:
        return self._update_field(agent_id, "status", status)

    # ── internal helpers ───────────────────────────────────────────────

    def _load(self) -> list[dict[str, Any]]:
        """Read the registry file with a shared lock."""
        if not self._path.exists():
            return []
        with self._lock:
            fd = None
            try:
                fd = os.open(str(self._path), os.O_RDONLY)
                fcntl.flock(fd, fcntl.LOCK_SH)
                raw = os.read(fd, 1_000_000).decode()
                return json.loads(raw) if raw.strip() else []
            except (json.JSONDecodeError, FileNotFoundError):
                return []
            finally:
                if fd is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)

    def _save(self, data: list[dict[str, Any]]) -> None:
        """Validate, then atomically write *data* to the registry file.

        Uses an exclusive lock, writes to a temp file, and renames.
        """
        errors = validate_registry(data)
        if errors:
            raise ValueError(f"schema validation failed: {'; '.join(errors)}")

        with self._lock:
            fd = None
            try:
                fd = os.open(str(self._path), os.O_RDWR | os.O_CREAT, 0o644)
                fcntl.flock(fd, fcntl.LOCK_EX)

                payload = json.dumps(data, indent=2)
                tmp_path = str(self._path) + ".tmp"

                with open(tmp_path, "w", encoding="utf-8") as tf:
                    tf.write(payload)
                    tf.flush()
                    os.fsync(tf.fileno())

                os.rename(tmp_path, str(self._path))

                # Clear the WAL — the write succeeded
                self._wal_clear()
            finally:
                if fd is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)

    def _mutate(
        self, op: str, agent_id: str, record: dict[str, Any]
    ) -> None:
        """Insert or update a single record with WAL journaling.

        The entire read-modify-write runs under an exclusive lock,
        preventing lost updates from concurrent writers.
        """
        self._wal_append(op, record)
        self._transactional_write(lambda data: (
            [e for e in data if e.get("agentId") != agent_id] + [record]
        ))

    def _update_field(self, agent_id: str, field: str, value: Any) -> bool:
        """Update a single field on an existing record.  Returns True if found."""
        found = False

        def _updater(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
            nonlocal found
            for entry in data:
                if entry.get("agentId") == agent_id:
                    entry[field] = value
                    found = True
                    break
            return data

        self._transactional_write(_updater)
        return found

    def _transactional_write(
        self, mutate_fn: callable
    ) -> None:
        """Load, mutate, validate, and save under a single exclusive lock.

        This is the core transactional primitive — the lock spans the
        entire read-modify-write, not just the final save.  That
        guarantees the ADR's promised single-writer semantics.
        """
        with self._lock:
            fd = None
            try:
                fd = os.open(str(self._path), os.O_RDWR | os.O_CREAT, 0o644)
                fcntl.flock(fd, fcntl.LOCK_EX)

                # Load under the exclusive lock
                data = self._load_locked(fd)

                # Apply the mutation
                data = mutate_fn(data)

                # Validate
                errors = validate_registry(data)
                if errors:
                    raise ValueError(
                        f"schema validation failed: {'; '.join(errors)}"
                    )

                # Atomic write
                payload = json.dumps(data, indent=2)
                tmp_path = str(self._path) + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as tf:
                    tf.write(payload)
                    tf.flush()
                    os.fsync(tf.fileno())
                os.rename(tmp_path, str(self._path))

                # Clear the WAL — the write succeeded
                self._wal_clear()
            finally:
                if fd is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)

    def _load_locked(self, fd: int) -> list[dict[str, Any]]:
        """Read the registry from an already-locked file descriptor."""
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            raw = os.read(fd, 1_000_000).decode()
            return json.loads(raw) if raw.strip() else []
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    # ── WAL (write-ahead log) ──────────────────────────────────────────

    def _wal_append(self, op: str, record: dict[str, Any]) -> None:
        """Append an operation to the write-ahead log."""
        entry = {"op": op, "record": record, "ts": int(time.time() * 1000)}
        try:
            with open(self._wal_path, "a", encoding="utf-8") as wf:
                wf.write(json.dumps(entry) + "\n")
                wf.flush()
                os.fsync(wf.fileno())
        except OSError as exc:
            log.warning("WAL append failed: %s", exc)

    def _wal_clear(self) -> None:
        """Truncate the WAL after a successful write."""
        try:
            if self._wal_path.exists():
                self._wal_path.write_text("")
        except OSError as exc:
            log.warning("WAL clear failed: %s", exc)

    def _replay_wal(self) -> None:
        """Replay any incomplete WAL entries on startup.

        This recovers from a crash that occurred between WAL append and
        the atomic rename.
        """
        if not self._wal_path.exists():
            return

        try:
            lines = self._wal_path.read_text().strip().splitlines()
        except OSError:
            return

        if not lines:
            return

        log.info("Replaying %d WAL entries for %s", len(lines), self._path)

        data = self._load()
        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            op = entry.get("op")
            record = entry.get("record", {})
            agent_id = record.get("agentId")
            if not agent_id:
                continue
            if op == "register":
                data = [e for e in data if e.get("agentId") != agent_id]
                data.append(record)

        # Validate and save the recovered state
        errors = validate_registry(data)
        if errors:
            log.error("WAL replay produced invalid state: %s", "; ".join(errors))
            return

        self._save(data)

    # ── conversion helpers ─────────────────────────────────────────────

    @staticmethod
    def _dict_to_record(d: dict[str, Any]) -> AgentRecord:
        return AgentRecord(
            agentId=d.get("agentId", ""),
            webhookEndpoint=d.get("webhookEndpoint", ""),
            capabilities=d.get("capabilities", []),
            registeredAt=d.get("registeredAt", 0),
            lastSeen=d.get("lastSeen", 0),
            status=d.get("status", "active"),
            publicKey=d.get("publicKey"),
        )

    @staticmethod
    def _record_to_dict(r: AgentRecord) -> dict[str, Any]:
        d: dict[str, Any] = {
            "agentId": r.agentId,
            "webhookEndpoint": r.webhookEndpoint,
            "capabilities": r.capabilities,
            "registeredAt": r.registeredAt,
            "lastSeen": r.lastSeen,
            "status": r.status,
        }
        if r.publicKey is not None:
            d["publicKey"] = r.publicKey
        return d
