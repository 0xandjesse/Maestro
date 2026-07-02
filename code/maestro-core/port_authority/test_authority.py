# nucleus/modules/port_authority/test_authority.py
"""Tests for the Port Authority module."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from nucleus.modules.port_authority import (
    PortAssignment,
    FilePortAuthority,
    PortMap,
)


# ── fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def tmp_port_map_path():
    fd, path = tempfile.mkstemp(suffix=".json", prefix="test_port_map_")
    os.close(fd)
    Path(path).write_text(json.dumps({
        "version": "1.0.0",
        "last_updated": "2026-06-30T00:00:00Z",
        "agents": {
            "songbird": {"transport_port": 3842, "gateway_port": 8649},
            "proteus": {"transport_port": 3846, "gateway_port": 8645},
        },
        "bridge": {"port": 8644},
    }))
    yield path
    for suffix in ("", ".tmp"):
        p = Path(path + suffix) if suffix else Path(path)
        if p.exists():
            p.unlink(missing_ok=True)


@pytest.fixture
def authority(tmp_port_map_path):
    return FilePortAuthority(tmp_port_map_path)


# ── basic CRUD ─────────────────────────────────────────────────────

class TestBasicCRUD:
    def test_resolve_existing(self, authority):
        a = authority.resolve("songbird")
        assert a.agent_id == "songbird"
        assert a.transport_port == 3842
        assert a.gateway_port == 8649

    def test_resolve_missing(self, authority):
        with pytest.raises(KeyError):
            authority.resolve("nobody")

    def test_assign_new(self, authority):
        a = authority.assign("cee-lo", 3851, 8651)
        assert a.agent_id == "cee-lo"
        assert a.transport_port == 3851
        assert a.gateway_port == 8651

        # Should now be resolvable
        resolved = authority.resolve("cee-lo")
        assert resolved.transport_port == 3851

    def test_assign_overwrite(self, authority):
        authority.assign("songbird", 9999, 9998)
        a = authority.resolve("songbird")
        assert a.transport_port == 9999
        assert a.gateway_port == 9998

    def test_list_all(self, authority):
        all_ports = authority.list_all()
        assert len(all_ports) == 2
        ids = {a.agent_id for a in all_ports}
        assert ids == {"songbird", "proteus"}


# ── persistence ────────────────────────────────────────────────────

class TestPersistence:
    def test_assign_persists(self, tmp_port_map_path):
        auth1 = FilePortAuthority(tmp_port_map_path)
        auth1.assign("cee-lo", 3851, 8651)

        # New instance should see the assignment
        auth2 = FilePortAuthority(tmp_port_map_path)
        a = auth2.resolve("cee-lo")
        assert a.transport_port == 3851

    def test_empty_file_creates_default(self, tmp_port_map_path):
        Path(tmp_port_map_path).write_text("")
        auth = FilePortAuthority(tmp_port_map_path)
        assert auth.list_all() == []

    def test_missing_file_creates_default(self):
        auth = FilePortAuthority("/tmp/nonexistent_port_map_test.json")
        assert auth.list_all() == []


# ── port availability ─────────────────────────────────────────────

class TestPortAvailability:
    def test_is_port_available(self, authority):
        # We can't easily mock ss, but we can verify the method runs
        result = authority.is_port_available(99999)
        # Port 99999 is almost certainly free
        assert result is True

    def test_verify_runs(self, authority):
        ok, errors = authority.verify()
        # verify() should run without crashing; actual result depends on system state
        assert isinstance(ok, bool)
        assert isinstance(errors, list)


# ── schema ─────────────────────────────────────────────────────────

class TestSchema:
    def test_port_map_roundtrip(self):
        data = {
            "version": "1.0.0",
            "last_updated": "2026-06-30T00:00:00Z",
            "agents": {"test": {"transport_port": 9000, "gateway_port": 9001}},
            "bridge": {"port": 9002},
        }
        pm = PortMap.from_dict(data)
        assert pm.to_dict() == data

    def test_port_map_defaults(self):
        pm = PortMap()
        assert pm.version == "1.0.0"
        assert pm.agents == {}
        assert pm.bridge == {}
