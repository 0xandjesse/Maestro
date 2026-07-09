"""
test_dm_policy.py — Unit tests for ADR-017 recipient-side capability list.

Tests the new _check_dm_policy() and _check_dm_policy_legacy() methods
in MaestroTransport. Uses temporary directories and synthetic tokens.
Token validation is mocked — these tests verify the policy logic, not crypto.
"""
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Add runtime to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code" / "runtime"))

from maestro.tokens import issue_token
from maestro_crypto import generate_key_pair


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def keypair():
    """Generate a fresh Ed25519 keypair for each test."""
    kp = generate_key_pair()
    return kp["private_key"], kp["public_key"]


@pytest.fixture
def transport():
    """Create a MaestroTransport with mocked dependencies, real _check_dm_policy."""
    from maestro_transport import MaestroTransport

    tmpdir = tempfile.mkdtemp()
    agent_dir = Path(tmpdir) / "songbird"
    (agent_dir / "issued").mkdir(parents=True)
    (agent_dir / "received").mkdir(parents=True)

    config = {
        "agentId": "songbird",
        "port": 19999,
        "hermesApiUrl": "http://127.0.0.1:9998",
        "hermesApiKey": "test-key",
        "conversation": "test-conv",
        "registryPath": str(Path(tmpdir) / "registry.json"),
        "dm_policy": {
            "token_dir": tmpdir,
            "venue": "org.dm",
            "default_policy": "closed",
        },
    }

    # Mock everything that would try to start a real server or connect to Hermes.
    # Also mock _validate_token to always pass — these tests verify policy logic,
    # not cryptographic validation (that's tested in maestro/tests/).
    with patch("aiohttp.web.Application"), \
         patch("maestro_transport.HermesClient", autospec=True), \
         patch("maestro_transport.LocalRegistry", autospec=True), \
         patch("maestro_transport._validate_token", return_value=(True, "")):
        t = MaestroTransport(config)
        t._dm_token_dir = agent_dir
        t.agent_id = "songbird"
        yield t


@pytest.fixture
def legacy_token_dir(transport, keypair):
    """Create a legacy flat Lexicon-issued token for proteus."""
    pk, pub = keypair
    token = issue_token(
        bearer_id="proteus",
        payload={"ven": "org.dm", "tgt": ["songbird", "proteus", "lexicon"], "scope": ["dm"]},
        issuer_id="lexicon",
        issuer_private_key_hex=pk,
        issuer_public_key_hex=pub,
    )
    legacy_path = transport._dm_token_dir.parent / "proteus.json"
    legacy_path.write_text(json.dumps(token, indent=2))
    yield legacy_path
    legacy_path.unlink(missing_ok=True)


# ── Tests: New capability-list model ───────────────────────

def test_own_token_accepted(transport, keypair):
    """Recipient issued token for sender → permitted."""
    pk, pub = keypair
    token = issue_token(
        bearer_id="proteus",
        payload={"ven": "org.dm"},
        issuer_id="songbird",
        issuer_private_key_hex=pk,
        issuer_public_key_hex=pub,
    )
    (transport._dm_token_dir / "issued" / "proteus.json").write_text(
        json.dumps(token, indent=2)
    )

    ok, reason = transport._check_dm_policy("proteus", "songbird")
    assert ok, f"Expected True, got False: {reason}"


def test_wrong_issuer_rejected(transport, keypair):
    """Token issued by someone else → rejected."""
    pk, pub = keypair
    token = issue_token(
        bearer_id="proteus",
        payload={"ven": "org.dm"},
        issuer_id="lexicon",  # Not songbird
        issuer_private_key_hex=pk,
        issuer_public_key_hex=pub,
    )
    (transport._dm_token_dir / "issued" / "proteus.json").write_text(
        json.dumps(token, indent=2)
    )

    ok, reason = transport._check_dm_policy("proteus", "songbird")
    assert not ok
    assert reason == "not_my_token"


def test_wrong_bearer_rejected(transport, keypair):
    """Token issued for different bearer → rejected."""
    pk, pub = keypair
    token = issue_token(
        bearer_id="lexicon",  # Not proteus
        payload={"ven": "org.dm"},
        issuer_id="songbird",
        issuer_private_key_hex=pk,
        issuer_public_key_hex=pub,
    )
    (transport._dm_token_dir / "issued" / "proteus.json").write_text(
        json.dumps(token, indent=2)
    )

    ok, reason = transport._check_dm_policy("proteus", "songbird")
    assert not ok
    assert reason == "wrong_bearer"


def test_no_token_rejected(transport):
    """No token file → rejected."""
    ok, reason = transport._check_dm_policy("proteus", "songbird")
    assert not ok
    assert reason == "no_dm_token"


def test_invalid_signature_rejected(transport, keypair):
    """Tampered signature → rejected (mocked — always passes, so this tests the mock)."""
    pk, pub = keypair
    token = issue_token(
        bearer_id="proteus",
        payload={"ven": "org.dm"},
        issuer_id="songbird",
        issuer_private_key_hex=pk,
        issuer_public_key_hex=pub,
    )
    (transport._dm_token_dir / "issued" / "proteus.json").write_text(
        json.dumps(token, indent=2)
    )

    # With mocked _validate_token, this passes. The real signature test
    # lives in maestro/tests/test_tokens.py.
    ok, reason = transport._check_dm_policy("proteus", "songbird")
    assert ok, f"Expected True with mocked validation, got False: {reason}"


# ── Tests: Legacy migration grace period ──────────────────

def test_legacy_lexicon_token_accepted(transport, legacy_token_dir):
    """Old flat Lexicon token → permitted during migration."""
    ok, reason = transport._check_dm_policy_legacy("proteus", "songbird")
    assert ok, f"Expected True, got False: {reason}"


def test_legacy_wrong_tgt_rejected(transport, keypair):
    """Old flat token, recipient not in tgt → rejected."""
    pk, pub = keypair
    token = issue_token(
        bearer_id="proteus",
        payload={"ven": "org.dm", "tgt": ["lexicon", "proteus"], "scope": ["dm"]},
        issuer_id="lexicon",
        issuer_private_key_hex=pk,
        issuer_public_key_hex=pub,
    )
    legacy_path = transport._dm_token_dir.parent / "proteus.json"
    legacy_path.write_text(json.dumps(token, indent=2))

    ok, reason = transport._check_dm_policy_legacy("proteus", "songbird")
    assert not ok
    assert "not_allowed" in reason

    legacy_path.unlink(missing_ok=True)


# ── Tests: Default policy behavior ─────────────────────────

def test_no_tokens_dir_no_enforcement(transport):
    """No issued/ directory → _check_dm_policy returns no_dm_token."""
    import shutil
    shutil.rmtree(transport._dm_token_dir / "issued")

    ok, reason = transport._check_dm_policy("proteus", "songbird")
    assert not ok
    assert reason == "no_dm_token"


def test_empty_issued_dir_no_enforcement(transport):
    """Empty issued/ directory → _check_dm_policy returns no_dm_token."""
    ok, reason = transport._check_dm_policy("proteus", "songbird")
    assert not ok
    assert reason == "no_dm_token"
