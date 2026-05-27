"""test_sync.py — verify stormtrooper transport copies are byte-identical to canonical."""

import hashlib
from pathlib import Path

CANONICAL = Path("/home/andjesse/maestro-sdk/runtime")
STORM = Path("/home/andjesse/maestro-sdk/runtime/maestro_transports/stormtrooper")

FILES_TO_SYNC = [
    "hermes_memory.py",
    "maestro_transport.py",
    "maestro_transport_clean.py",
    "maestro_gateway_bridge.py",
    "maestro_status.py",
    "maestro_team_status.py",
    "smoke_server.py",
    "atomic_bb_io.py",
]


def _hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_all_copies_exist():
    for name in FILES_TO_SYNC:
        assert (STORM / name).exists(), f"missing {name} in stormtrooper copy"
        assert (CANONICAL / name).exists(), f"missing {name} in canonical"


def test_all_copies_identical():
    mismatches = []
    for name in FILES_TO_SYNC:
        c_hash = _hash(CANONICAL / name)
        s_hash = _hash(STORM / name)
        if c_hash != s_hash:
            mismatches.append(name)
    assert not mismatches, f"byte-divergent files: {mismatches}"


def test_stormtrooper_has_tests_too():
    tests_dir = STORM.parent.parent / "tests"
    assert tests_dir.exists(), "tests directory should exist"
    py_tests = list(tests_dir.glob("test_*.py"))
    assert len(py_tests) >= 3, f"expected >=3 test files, got {len(py_tests)}"


if __name__ == "__main__":
    test_all_copies_exist()
    print("PASS: all copies exist")
    test_all_copies_identical()
    print("PASS: all copies byte-identical")
    test_stormtrooper_has_tests_too()
    print("PASS: tests directory present")
    print("\nAll sync tests PASSED")
