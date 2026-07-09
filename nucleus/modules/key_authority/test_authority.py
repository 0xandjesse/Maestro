"""Tests for the Key Authority module.

Covers:
* Key pair generation (Ed25519)
* Sign and verify tokens
* Private key encryption/decryption (AES-256-GCM)
* Key revocation
* Key rotation
* Signing token authentication
* Token issuance and verification
* Schema validation
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from nucleus.modules.key_authority import (
    FileKeyAuthority,
    KeyPair,
    SignedToken,
    VerificationResult,
    validate_key_storage,
    validate_revocation_list,
)


# ── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for isolated key authority storage."""
    with tempfile.TemporaryDirectory(prefix="test_keyauth_") as td:
        yield td


@pytest.fixture
def authority(tmp_dir):
    """Return a FileKeyAuthority pointed at a temp directory."""
    return FileKeyAuthority(
        keys_dir=os.path.join(tmp_dir, "keys"),
        revocation_path=os.path.join(tmp_dir, "revoked_keys.json"),
        signing_tokens_path=os.path.join(tmp_dir, "signing_tokens.json"),
        issued_tokens_path=os.path.join(tmp_dir, "issued_tokens.json"),
        master_key_path=os.path.join(tmp_dir, ".master_key"),
    )


@pytest.fixture
def agent_with_key(authority):
    """Set up an agent with a key pair and signing token.

    Returns (authority, agent_id, keypair, signing_token).
    """
    agent_id = "test-agent-1"
    keypair = authority.generate_keypair(agent_id)
    bearer = "super-secret-token-12345"
    authority.setup_signing_token(agent_id, bearer)
    return authority, agent_id, keypair, bearer


# ── key generation ─────────────────────────────────────────────────────


class TestKeyGeneration:
    def test_generate_keypair(self, authority):
        kp = authority.generate_keypair("agent-1")
        assert isinstance(kp, KeyPair)
        assert kp.agent_id == "agent-1"
        assert len(kp.public_key) == 64  # Ed25519 public key = 32 bytes = 64 hex
        assert len(kp.private_key_encrypted) > 0
        assert kp.created_at > 0
        assert len(kp.key_id) == 16

    def test_generate_keypair_unique(self, authority):
        kp1 = authority.generate_keypair("agent-1")
        kp2 = authority.generate_keypair("agent-2")
        assert kp1.public_key != kp2.public_key
        assert kp1.key_id != kp2.key_id
        assert kp1.private_key_encrypted != kp2.private_key_encrypted

    def test_generate_keypair_persisted(self, authority):
        authority.generate_keypair("agent-1")
        pk = authority.get_public_key("agent-1")
        assert pk is not None
        assert len(pk) == 64

    def test_generate_keypair_empty_agent_id(self, authority):
        with pytest.raises(ValueError, match="agent_id"):
            authority.generate_keypair("")

    def test_get_public_key_missing(self, authority):
        assert authority.get_public_key("nobody") is None

    def test_generate_keypair_overwrites(self, authority):
        kp1 = authority.generate_keypair("agent-1")
        kp2 = authority.generate_keypair("agent-1")
        # New key should have different key_id
        assert kp1.key_id != kp2.key_id
        # Public key should be different
        assert kp1.public_key != kp2.public_key


# ── sign and verify ────────────────────────────────────────────────────


class TestSignAndVerify:
    def test_sign_and_verify(self, agent_with_key):
        authority, agent_id, kp, bearer = agent_with_key

        payload = {"action": "test", "data": "hello"}
        signed = authority.sign(agent_id, payload, bearer)

        assert isinstance(signed, SignedToken)
        assert signed.signer_agent_id == agent_id
        assert signed.signer_public_key == kp.public_key
        assert signed.payload == payload
        assert len(signed.signature) == 128  # Ed25519 sig = 64 bytes = 128 hex
        assert signed.issued_at > 0
        assert signed.expires_at is None

        result = authority.verify(signed)
        assert result.valid is True
        assert result.signer_agent_id == agent_id

    def test_sign_wrong_bearer(self, agent_with_key):
        authority, agent_id, kp, bearer = agent_with_key

        with pytest.raises(PermissionError, match="Invalid signing token"):
            authority.sign(agent_id, {"x": 1}, "wrong-token")

    def test_sign_missing_agent(self, authority):
        authority.setup_signing_token("ghost", "token")
        with pytest.raises(ValueError, match="No key pair"):
            authority.sign("ghost", {"x": 1}, "token")

    def test_verify_tampered_payload(self, agent_with_key):
        authority, agent_id, kp, bearer = agent_with_key

        signed = authority.sign(agent_id, {"action": "test"}, bearer)
        # Tamper with payload
        signed.payload = {"action": "evil"}
        result = authority.verify(signed)
        assert result.valid is False
        assert "failed" in result.reason.lower()

    def test_verify_tampered_signature(self, agent_with_key):
        authority, agent_id, kp, bearer = agent_with_key

        signed = authority.sign(agent_id, {"action": "test"}, bearer)
        # Tamper with signature
        signed.signature = "00" * 64
        result = authority.verify(signed)
        assert result.valid is False

    def test_verify_wrong_public_key(self, agent_with_key):
        authority, agent_id, kp, bearer = agent_with_key

        signed = authority.sign(agent_id, {"action": "test"}, bearer)
        # Replace public key with a different one
        signed.signer_public_key = "ab" * 32
        result = authority.verify(signed)
        assert result.valid is False

    def test_verify_expired_token(self, agent_with_key):
        authority, agent_id, kp, bearer = agent_with_key

        signed = authority.sign(agent_id, {"action": "test"}, bearer)
        signed.expires_at = 1  # way in the past
        result = authority.verify(signed)
        assert result.valid is False
        assert "expired" in result.reason.lower()

    def test_sign_deterministic_verify(self, agent_with_key):
        """Same payload signed twice produces different signatures, but both
        verify correctly."""
        authority, agent_id, kp, bearer = agent_with_key

        payload = {"action": "test"}
        signed1 = authority.sign(agent_id, payload, bearer)
        time.sleep(0.01)
        signed2 = authority.sign(agent_id, payload, bearer)

        # Different token_ids and signatures (different timestamps)
        assert signed1.token_id != signed2.token_id
        # Both verify
        assert authority.verify(signed1).valid
        assert authority.verify(signed2).valid


# ── revocation ─────────────────────────────────────────────────────────


class TestRevocation:
    def test_revoke_key(self, agent_with_key):
        authority, agent_id, kp, bearer = agent_with_key

        assert authority.is_revoked(kp.key_id) is False
        result = authority.revoke_key(agent_id, kp.key_id)
        assert result is True
        assert authority.is_revoked(kp.key_id) is True

    def test_revoke_already_revoked(self, agent_with_key):
        authority, agent_id, kp, bearer = agent_with_key

        authority.revoke_key(agent_id, kp.key_id)
        result = authority.revoke_key(agent_id, kp.key_id)
        assert result is False

    def test_sign_with_revoked_key(self, agent_with_key):
        authority, agent_id, kp, bearer = agent_with_key

        authority.revoke_key(agent_id, kp.key_id)
        with pytest.raises(PermissionError, match="revoked"):
            authority.sign(agent_id, {"action": "test"}, bearer)

    def test_verify_revoked_key(self, agent_with_key):
        authority, agent_id, kp, bearer = agent_with_key

        signed = authority.sign(agent_id, {"action": "test"}, bearer)
        # Revoke after signing
        authority.revoke_key(agent_id, kp.key_id)
        result = authority.verify(signed)
        assert result.valid is False
        assert "revoked" in result.reason.lower()

    def test_revocation_persisted(self, agent_with_key, tmp_dir):
        authority, agent_id, kp, bearer = agent_with_key

        authority.revoke_key(agent_id, kp.key_id)

        # Create a new authority pointing at the same files
        authority2 = FileKeyAuthority(
            keys_dir=os.path.join(tmp_dir, "keys"),
            revocation_path=os.path.join(tmp_dir, "revoked_keys.json"),
            signing_tokens_path=os.path.join(tmp_dir, "signing_tokens.json"),
            issued_tokens_path=os.path.join(tmp_dir, "issued_tokens.json"),
            master_key_path=os.path.join(tmp_dir, ".master_key"),
        )
        assert authority2.is_revoked(kp.key_id) is True


# ── key rotation ───────────────────────────────────────────────────────


class TestKeyRotation:
    def test_rotate_keypair(self, agent_with_key):
        authority, agent_id, old_kp, bearer = agent_with_key

        new_kp = authority.rotate_keypair(agent_id)

        # Old key should be revoked
        assert authority.is_revoked(old_kp.key_id) is True

        # New key should be different
        assert new_kp.key_id != old_kp.key_id
        assert new_kp.public_key != old_kp.public_key

        # New key should work (re-setup bearer since rotate doesn't change it)
        authority.setup_signing_token(agent_id, bearer)
        signed = authority.sign(agent_id, {"action": "test"}, bearer)
        assert authority.verify(signed).valid

    def test_rotate_no_previous_key(self, authority):
        """Rotating an agent with no previous key just generates a new one."""
        authority.setup_signing_token("new-agent", "token")
        kp = authority.rotate_keypair("new-agent")
        assert isinstance(kp, KeyPair)
        assert kp.agent_id == "new-agent"


# ── token issuance ─────────────────────────────────────────────────────


class TestTokenIssuance:
    def test_issue_and_verify_token(self, agent_with_key):
        authority, agent_id, kp, bearer = agent_with_key

        issued = authority.issue_token(
            issuer_id=agent_id,
            subject_id="subject-1",
            scope=["read", "write"],
            ttl_hours=24,
        )

        assert isinstance(issued, SignedToken)
        assert issued.payload["iss"] == agent_id
        assert issued.payload["sub"] == "subject-1"
        assert issued.payload["scope"] == ["read", "write"]
        assert issued.payload["exp"] > issued.payload["iat"]

        # Verify the issued token
        result = authority.verify_issued_token(issued.token_id)
        assert result.valid is True
        assert result.signer_agent_id == agent_id

    def test_verify_issued_token_not_found(self, authority):
        result = authority.verify_issued_token("nonexistent")
        assert result.valid is False
        assert "not found" in result.reason.lower()

    def test_issue_token_expiry(self, agent_with_key):
        authority, agent_id, kp, bearer = agent_with_key

        # Issue with 0-hour TTL (expired immediately)
        issued = authority.issue_token(
            issuer_id=agent_id,
            subject_id="subject-1",
            scope=["read"],
            ttl_hours=0,
        )

        # Should be expired
        result = authority.verify_issued_token(issued.token_id)
        assert result.valid is False
        assert "expired" in result.reason.lower()


# ── signing token management ────────────────────────────────────────────


class TestSigningTokens:
    def test_setup_and_verify(self, authority):
        authority.setup_signing_token("agent-1", "my-secret-token")
        authority.generate_keypair("agent-1")
        signed = authority.sign("agent-1", {"x": 1}, "my-secret-token")
        assert authority.verify(signed).valid

    def test_signing_token_wrong(self, authority):
        authority.setup_signing_token("agent-1", "correct-token")
        authority.generate_keypair("agent-1")
        with pytest.raises(PermissionError):
            authority.sign("agent-1", {"x": 1}, "wrong-token")

    def test_signing_token_persisted(self, authority, tmp_dir):
        authority.setup_signing_token("agent-1", "my-token")
        authority.generate_keypair("agent-1")

        # New authority instance with same files
        authority2 = FileKeyAuthority(
            keys_dir=os.path.join(tmp_dir, "keys"),
            revocation_path=os.path.join(tmp_dir, "revoked_keys.json"),
            signing_tokens_path=os.path.join(tmp_dir, "signing_tokens.json"),
            issued_tokens_path=os.path.join(tmp_dir, "issued_tokens.json"),
            master_key_path=os.path.join(tmp_dir, ".master_key"),
        )
        signed = authority2.sign("agent-1", {"x": 1}, "my-token")
        assert authority2.verify(signed).valid


# ── master key persistence ─────────────────────────────────────────────


class TestMasterKey:
    def test_master_key_persisted(self, tmp_dir):
        authority1 = FileKeyAuthority(
            keys_dir=os.path.join(tmp_dir, "keys"),
            revocation_path=os.path.join(tmp_dir, "revoked_keys.json"),
            signing_tokens_path=os.path.join(tmp_dir, "signing_tokens.json"),
            issued_tokens_path=os.path.join(tmp_dir, "issued_tokens.json"),
            master_key_path=os.path.join(tmp_dir, ".master_key"),
        )

        kp = authority1.generate_keypair("agent-1")
        authority1.setup_signing_token("agent-1", "token")

        # New authority with same master key should be able to decrypt
        authority2 = FileKeyAuthority(
            keys_dir=os.path.join(tmp_dir, "keys"),
            revocation_path=os.path.join(tmp_dir, "revoked_keys.json"),
            signing_tokens_path=os.path.join(tmp_dir, "signing_tokens.json"),
            issued_tokens_path=os.path.join(tmp_dir, "issued_tokens.json"),
            master_key_path=os.path.join(tmp_dir, ".master_key"),
        )

        signed = authority2.sign("agent-1", {"action": "test"}, "token")
        assert authority2.verify(signed).valid

    def test_master_key_regenerated_on_corruption(self, tmp_dir):
        master_key_path = os.path.join(tmp_dir, ".master_key")

        authority1 = FileKeyAuthority(
            keys_dir=os.path.join(tmp_dir, "keys"),
            revocation_path=os.path.join(tmp_dir, "revoked_keys.json"),
            signing_tokens_path=os.path.join(tmp_dir, "signing_tokens.json"),
            issued_tokens_path=os.path.join(tmp_dir, "issued_tokens.json"),
            master_key_path=master_key_path,
        )

        kp = authority1.generate_keypair("agent-1")
        authority1.setup_signing_token("agent-1", "token")

        # Corrupt the master key
        Path(master_key_path).write_bytes(b"corrupted!!")

        # New authority will regenerate master key
        authority2 = FileKeyAuthority(
            keys_dir=os.path.join(tmp_dir, "keys"),
            revocation_path=os.path.join(tmp_dir, "revoked_keys.json"),
            signing_tokens_path=os.path.join(tmp_dir, "signing_tokens.json"),
            issued_tokens_path=os.path.join(tmp_dir, "issued_tokens.json"),
            master_key_path=master_key_path,
        )

        # Old encrypted key can't be decrypted with new master key
        with pytest.raises(ValueError, match="decrypt"):
            authority2.sign("agent-1", {"x": 1}, "token")


# ── schema validation ──────────────────────────────────────────────────


class TestSchemaValidation:
    def test_valid_key_storage(self):
        errors = validate_key_storage({
            "agent-1": {
                "agent_id": "agent-1",
                "public_key": "a" * 64,
                "private_key_encrypted": "base64stuff",
                "created_at": 1000,
                "key_id": "abcd1234abcd1234",
            }
        })
        assert errors == []

    def test_key_storage_missing_fields(self):
        errors = validate_key_storage({
            "agent-1": {
                "agent_id": "agent-1",
            }
        })
        assert len(errors) > 0

    def test_key_storage_bad_public_key(self):
        errors = validate_key_storage({
            "agent-1": {
                "agent_id": "agent-1",
                "public_key": "xyz",  # not hex, wrong length
                "private_key_encrypted": "stuff",
                "created_at": 1000,
                "key_id": "abcd1234",
            }
        })
        assert any("public_key" in e for e in errors)

    def test_key_storage_not_a_dict(self):
        errors = validate_key_storage(["not", "a", "dict"])
        assert any("object" in e for e in errors)

    def test_valid_revocation_list(self):
        errors = validate_revocation_list([
            {
                "key_id": "abcd1234abcd1234",
                "agent_id": "agent-1",
                "revoked_at": 1000,
                "reason": "rotation",
            }
        ])
        assert errors == []

    def test_revocation_list_missing_fields(self):
        errors = validate_revocation_list([
            {"key_id": "abcd1234"}
        ])
        assert len(errors) > 0

    def test_revocation_list_duplicate(self):
        errors = validate_revocation_list([
            {"key_id": "dup", "agent_id": "a", "revoked_at": 1},
            {"key_id": "dup", "agent_id": "b", "revoked_at": 2},
        ])
        assert any("duplicate" in e for e in errors)

    def test_revocation_list_not_a_list(self):
        errors = validate_revocation_list({"not": "a list"})
        assert any("array" in e for e in errors)


# ── edge cases ─────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_sign_large_payload(self, agent_with_key):
        authority, agent_id, kp, bearer = agent_with_key

        large_payload = {"data": "x" * 10000, "nested": {"a": [1, 2, 3] * 100}}
        signed = authority.sign(agent_id, large_payload, bearer)
        assert authority.verify(signed).valid

    def test_sign_empty_payload(self, agent_with_key):
        authority, agent_id, kp, bearer = agent_with_key

        signed = authority.sign(agent_id, {}, bearer)
        assert authority.verify(signed).valid

    def test_multiple_agents(self, authority):
        authority.generate_keypair("alice")
        authority.generate_keypair("bob")
        authority.setup_signing_token("alice", "alice-token")
        authority.setup_signing_token("bob", "bob-token")

        alice_signed = authority.sign("alice", {"from": "alice"}, "alice-token")
        bob_signed = authority.sign("bob", {"from": "bob"}, "bob-token")

        assert authority.verify(alice_signed).valid
        assert authority.verify(bob_signed).valid

        # Cross-verify: alice's token with bob's public key should fail
        alice_signed.signer_public_key = bob_signed.signer_public_key
        result = authority.verify(alice_signed)
        assert result.valid is False

    def test_key_file_persisted(self, authority):
        kp = authority.generate_keypair("agent-1")
        key_path = authority._key_path("agent-1")
        assert key_path.exists()
        # Key file should exist and be readable
        content = key_path.read_text()
        data = json.loads(content)
        assert data["agent_id"] == "agent-1"
        assert data["public_key"] == kp.public_key
