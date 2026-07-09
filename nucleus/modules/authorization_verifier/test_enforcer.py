"""Tests for the Authorization Verifier module.

Covers:
* Policy checks — all AuthResult variants
* Token issuance and lifecycle
* Token revocation
* Token verification (signature, expiry)
* Scope checking
* Schema validation
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from nucleus.modules.authorization_verifier import (
    AuthorizationVerifier,
    AuthResult,
    AuthToken,
    FileAuthorizationVerifier,
    validate_revocation_list,
    validate_token_entry,
)
from nucleus.modules.key_authority import FileKeyAuthority
from nucleus.modules.registry_manager import FileRegistryManager


# ── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for isolated storage."""
    with tempfile.TemporaryDirectory(prefix="test_dmenf_") as td:
        yield td


@pytest.fixture
def key_authority(tmp_dir):
    """Return a FileKeyAuthority pointed at a temp directory."""
    return FileKeyAuthority(
        keys_dir=os.path.join(tmp_dir, "keys"),
        revocation_path=os.path.join(tmp_dir, "revoked_keys.json"),
        signing_tokens_path=os.path.join(tmp_dir, "signing_tokens.json"),
        issued_tokens_path=os.path.join(tmp_dir, "issued_tokens.json"),
        master_key_path=os.path.join(tmp_dir, ".master_key"),
    )


@pytest.fixture
def registry(tmp_dir):
    """Return a FileRegistryManager pointed at a temp file."""
    reg_path = os.path.join(tmp_dir, "registry.json")
    Path(reg_path).write_text("[]")
    return FileRegistryManager(reg_path)


@pytest.fixture
def enforcer(key_authority, registry, tmp_dir):
    """Return a FileAuthorizationVerifier with isolated storage."""
    return FileAuthorizationVerifier(
        key_authority=key_authority,
        registry=registry,
        tokens_dir=os.path.join(tmp_dir, "dm_tokens"),
        revocation_path=os.path.join(tmp_dir, "revoked_tokens.json"),
    )


@pytest.fixture
def agents_with_keys(key_authority, registry):
    """Register two agents with key pairs and return their IDs."""
    alice = "alice-agent"
    bob = "bob-agent"

    key_authority.generate_keypair(alice)
    key_authority.generate_keypair(bob)

    registry.register(alice, "http://127.0.0.1:9001/message")
    registry.register(bob, "http://127.0.0.1:9002/message")

    return alice, bob


@pytest.fixture
def valid_token(enforcer, agents_with_keys):
    """Issue a valid token from alice to bob and return it."""
    alice, bob = agents_with_keys
    return enforcer.issue_token(
        issuer_id=alice,
        subject_id=bob,
        scope=["dm:send", "dm:receive"],
        ttl_hours=24,
    )


# ── policy checks ──────────────────────────────────────────────────────


class TestCheckPolicy:
    def test_allows_valid_token(self, enforcer, agents_with_keys, valid_token):
        alice, bob = agents_with_keys
        # Token subject is bob — bob is the one who can use it
        result = enforcer.verify(bob, alice, valid_token)
        assert result == AuthResult.VALID

    def test_denies_missing_token(self, enforcer, agents_with_keys):
        alice, bob = agents_with_keys
        result = enforcer.verify(alice, bob, None)
        assert result == AuthResult.NO_TOKEN

    def test_denies_expired_token(self, enforcer, agents_with_keys):
        alice, bob = agents_with_keys
        # Issue a token with 0 TTL — it expires immediately
        token = enforcer.issue_token(
            issuer_id=alice,
            subject_id=bob,
            scope=["dm:send", "dm:receive"],
            ttl_hours=0,
        )
        # Force expiry by waiting a tiny bit
        time.sleep(0.01)
        result = enforcer.verify(bob, alice, token)
        assert result == AuthResult.EXPIRED

    def test_denies_revoked_token(self, enforcer, agents_with_keys, valid_token):
        alice, bob = agents_with_keys
        enforcer.revoke_token(valid_token.token_id)
        result = enforcer.verify(bob, alice, valid_token)
        assert result == AuthResult.REVOKED

    def test_denies_missing_send_scope(self, enforcer, agents_with_keys):
        alice, bob = agents_with_keys
        token = enforcer.issue_token(
            issuer_id=alice,
            subject_id=bob,
            scope=["dm:receive"],  # no dm:send
            ttl_hours=24,
        )
        result = enforcer.verify(bob, alice, token)
        assert result == AuthResult.SCOPE_INSUFFICIENT

    def test_send_only_scope_allows_even_when_subject_is_recipient(
        self, enforcer, agents_with_keys
    ):
        alice, bob = agents_with_keys
        token = enforcer.issue_token(
            issuer_id=alice,
            subject_id=bob,
            scope=["dm:send"],  # no dm:receive
            ttl_hours=24,
        )
        # bob is the subject — bob can send with dm:send scope
        result = enforcer.verify(bob, alice, token)
        assert result == AuthResult.VALID

    def test_denies_key_mismatch(self, enforcer, agents_with_keys, valid_token):
        alice, bob = agents_with_keys
        # Tamper with the signature
        tampered = AuthToken(
            token_id=valid_token.token_id,
            issuer=valid_token.issuer,
            subject=valid_token.subject,
            scope=valid_token.scope,
            issued_at=valid_token.issued_at,
            expires_at=valid_token.expires_at,
            signature="00" * 64,  # bogus signature
            public_key=valid_token.public_key,
        )
        result = enforcer.verify(bob, alice, tampered)
        assert result == AuthResult.KEY_MISMATCH


# ── token issuance ─────────────────────────────────────────────────────


class TestIssueToken:
    def test_creates_valid_token(self, enforcer, agents_with_keys):
        alice, bob = agents_with_keys
        token = enforcer.issue_token(
            issuer_id=alice,
            subject_id=bob,
            scope=["dm:send", "dm:receive"],
            ttl_hours=24,
        )
        assert isinstance(token, AuthToken)
        assert len(token.token_id) == 16
        assert token.issuer == alice
        assert token.subject == bob
        assert token.scope == ["dm:send", "dm:receive"]
        assert token.issued_at > 0
        assert token.expires_at > token.issued_at
        assert len(token.signature) == 128  # Ed25519 sig = 64 bytes = 128 hex
        assert len(token.public_key) == 64  # Ed25519 pub = 32 bytes = 64 hex

    def test_token_is_verifiable(self, enforcer, agents_with_keys):
        alice, bob = agents_with_keys
        token = enforcer.issue_token(
            issuer_id=alice,
            subject_id=bob,
            scope=["dm:send", "dm:receive"],
            ttl_hours=24,
        )
        valid, reason = enforcer.verify_token(token)
        assert valid, f"Token should be valid but got: {reason}"
        assert reason == "Token is valid"

    def test_issuer_without_key_raises(self, enforcer, registry):
        """Issuing without a key pair should raise ValueError."""
        registry.register("no-key-agent", "http://127.0.0.1:9003/message")
        with pytest.raises(ValueError, match="no key pair"):
            enforcer.issue_token(
                issuer_id="no-key-agent",
                subject_id="bob-agent",
                scope=["dm:send"],
                ttl_hours=24,
            )

    def test_default_ttl_is_24_hours(self, enforcer, agents_with_keys):
        alice, bob = agents_with_keys
        token = enforcer.issue_token(
            issuer_id=alice,
            subject_id=bob,
            scope=["dm:send", "dm:receive"],
        )
        # 24 hours in ms
        expected_window = 24 * 3600 * 1000
        actual = token.expires_at - token.issued_at
        # Allow 1 second tolerance
        assert abs(actual - expected_window) < 1000


# ── token revocation ───────────────────────────────────────────────────


class TestRevokeToken:
    def test_revoke_existing_token(self, enforcer, valid_token):
        result = enforcer.revoke_token(valid_token.token_id)
        assert result is True

    def test_revoke_nonexistent_token(self, enforcer):
        result = enforcer.revoke_token("nonexistent-id")
        assert result is False

    def test_revoke_already_revoked(self, enforcer, valid_token):
        enforcer.revoke_token(valid_token.token_id)
        result = enforcer.revoke_token(valid_token.token_id)
        assert result is False  # already revoked

    def test_revoked_token_fails_policy(self, enforcer, agents_with_keys, valid_token):
        alice, bob = agents_with_keys
        enforcer.revoke_token(valid_token.token_id)
        result = enforcer.verify(alice, bob, valid_token)
        assert result == AuthResult.REVOKED

    def test_revoked_token_fails_verify(self, enforcer, valid_token):
        enforcer.revoke_token(valid_token.token_id)
        valid, reason = enforcer.verify_token(valid_token)
        assert not valid
        assert "revoked" in reason.lower()


# ── token verification ─────────────────────────────────────────────────


class TestVerifyToken:
    def test_verify_valid_token(self, enforcer, valid_token):
        valid, reason = enforcer.verify_token(valid_token)
        assert valid
        assert reason == "Token is valid"

    def test_verify_expired_token(self, enforcer, agents_with_keys):
        alice, bob = agents_with_keys
        token = enforcer.issue_token(
            issuer_id=alice,
            subject_id=bob,
            scope=["dm:send", "dm:receive"],
            ttl_hours=0,
        )
        time.sleep(0.01)
        valid, reason = enforcer.verify_token(token)
        assert not valid
        assert "expired" in reason.lower()

    def test_verify_tampered_signature(self, enforcer, valid_token):
        tampered = AuthToken(
            token_id=valid_token.token_id,
            issuer=valid_token.issuer,
            subject=valid_token.subject,
            scope=valid_token.scope,
            issued_at=valid_token.issued_at,
            expires_at=valid_token.expires_at,
            signature="ab" * 64,  # bogus
            public_key=valid_token.public_key,
        )
        valid, reason = enforcer.verify_token(tampered)
        assert not valid

    def test_verify_tampered_public_key(self, enforcer, agents_with_keys):
        alice, bob = agents_with_keys
        token = enforcer.issue_token(
            issuer_id=alice,
            subject_id=bob,
            scope=["dm:send", "dm:receive"],
            ttl_hours=24,
        )
        tampered = AuthToken(
            token_id=token.token_id,
            issuer=token.issuer,
            subject=token.subject,
            scope=token.scope,
            issued_at=token.issued_at,
            expires_at=token.expires_at,
            signature=token.signature,
            public_key="cd" * 32,  # bogus public key
        )
        valid, reason = enforcer.verify_token(tampered)
        assert not valid


# ── scope checking ─────────────────────────────────────────────────────


class TestScopeChecking:
    def test_send_only_scope_allows_sender(self, enforcer, agents_with_keys):
        alice, bob = agents_with_keys
        token = enforcer.issue_token(
            issuer_id=alice,
            subject_id=bob,
            scope=["dm:send"],
            ttl_hours=24,
        )
        # bob (subject) has dm:send — should be allowed
        result = enforcer.verify(bob, alice, token)
        assert result == AuthResult.VALID

    def test_receive_only_scope_denies_sender(self, enforcer, agents_with_keys):
        alice, bob = agents_with_keys
        token = enforcer.issue_token(
            issuer_id=alice,
            subject_id=bob,
            scope=["dm:receive"],
            ttl_hours=24,
        )
        result = enforcer.verify(bob, alice, token)
        assert result == AuthResult.SCOPE_INSUFFICIENT

    def test_both_scopes_allows(self, enforcer, agents_with_keys):
        alice, bob = agents_with_keys
        token = enforcer.issue_token(
            issuer_id=alice,
            subject_id=bob,
            scope=["dm:send", "dm:receive"],
            ttl_hours=24,
        )
        result = enforcer.verify(bob, alice, token)
        assert result == AuthResult.VALID


# ── token lifecycle ────────────────────────────────────────────────────


class TestTokenLifecycle:
    def test_full_lifecycle(self, enforcer, agents_with_keys):
        alice, bob = agents_with_keys

        # Issue
        token = enforcer.issue_token(
            issuer_id=alice,
            subject_id=bob,
            scope=["dm:send", "dm:receive"],
            ttl_hours=1,
        )

        # Verify
        valid, reason = enforcer.verify_token(token)
        assert valid

        # Policy allows
        result = enforcer.verify(bob, alice, token)
        assert result == AuthResult.VALID

        # Revoke
        assert enforcer.revoke_token(token.token_id) is True

        # Policy denies after revoke
        result = enforcer.verify(bob, alice, token)
        assert result == AuthResult.REVOKED

        # Verify denies after revoke
        valid, reason = enforcer.verify_token(token)
        assert not valid

    def test_multiple_tokens_independent(self, enforcer, agents_with_keys):
        alice, bob = agents_with_keys

        token1 = enforcer.issue_token(alice, bob, ["dm:send", "dm:receive"])
        token2 = enforcer.issue_token(alice, bob, ["dm:send", "dm:receive"])

        # Revoke only token1
        enforcer.revoke_token(token1.token_id)

        # token1 should be denied
        assert enforcer.verify(bob, alice, token1) == AuthResult.REVOKED

        # token2 should still be allowed
        assert enforcer.verify(bob, alice, token2) == AuthResult.VALID


# ── schema validation ──────────────────────────────────────────────────


class TestSchemaValidation:
    def test_validate_valid_token_entry(self):
        entry = {
            "token_id": "abc123",
            "issuer": "alice",
            "subject": "bob",
            "scope": ["dm:send", "dm:receive"],
            "issued_at": 1000000,
            "expires_at": 2000000,
            "signature": "a" * 128,
            "public_key": "b" * 64,
        }
        errors = validate_token_entry(entry)
        assert errors == []

    def test_validate_token_entry_missing_fields(self):
        entry = {}
        errors = validate_token_entry(entry)
        assert len(errors) > 0

    def test_validate_token_entry_bad_signature_length(self):
        entry = {
            "token_id": "abc",
            "issuer": "alice",
            "subject": "bob",
            "scope": ["dm:send"],
            "issued_at": 1,
            "expires_at": 2,
            "signature": "too-short",
            "public_key": "b" * 64,
        }
        errors = validate_token_entry(entry)
        assert any("signature" in e.lower() for e in errors)

    def test_validate_token_entry_bad_public_key_length(self):
        entry = {
            "token_id": "abc",
            "issuer": "alice",
            "subject": "bob",
            "scope": ["dm:send"],
            "issued_at": 1,
            "expires_at": 2,
            "signature": "a" * 128,
            "public_key": "too-short",
        }
        errors = validate_token_entry(entry)
        assert any("public_key" in e.lower() for e in errors)

    def test_validate_token_entry_empty_scope(self):
        entry = {
            "token_id": "abc",
            "issuer": "alice",
            "subject": "bob",
            "scope": [],
            "issued_at": 1,
            "expires_at": 2,
            "signature": "a" * 128,
            "public_key": "b" * 64,
        }
        errors = validate_token_entry(entry)
        assert any("scope" in e.lower() for e in errors)

    def test_validate_revocation_list_valid(self):
        data = [
            {"token_id": "tok1", "revoked_at": 1000, "reason": "test"},
            {"token_id": "tok2", "revoked_at": 2000, "reason": "test"},
        ]
        errors = validate_revocation_list(data)
        assert errors == []

    def test_validate_revocation_list_duplicate(self):
        data = [
            {"token_id": "tok1", "revoked_at": 1000, "reason": "test"},
            {"token_id": "tok1", "revoked_at": 2000, "reason": "test"},
        ]
        errors = validate_revocation_list(data)
        assert any("duplicate" in e.lower() for e in errors)

    def test_validate_revocation_list_not_a_list(self):
        errors = validate_revocation_list({"not": "a list"})
        assert len(errors) > 0
        assert any("array" in e.lower() for e in errors)


# ── all policy results enumerated ──────────────────────────────────────


class TestAllPolicyResults:
    """Ensure every AuthResult variant is reachable."""

    def test_allowed(self, enforcer, agents_with_keys, valid_token):
        alice, bob = agents_with_keys
        assert enforcer.verify(bob, alice, valid_token) == AuthResult.VALID

    def test_denied_no_token(self, enforcer, agents_with_keys):
        alice, bob = agents_with_keys
        assert enforcer.verify(alice, bob, None) == AuthResult.NO_TOKEN

    def test_denied_expired(self, enforcer, agents_with_keys):
        alice, bob = agents_with_keys
        token = enforcer.issue_token(alice, bob, ["dm:send", "dm:receive"], ttl_hours=0)
        time.sleep(0.01)
        assert enforcer.verify(bob, alice, token) == AuthResult.EXPIRED

    def test_denied_revoked(self, enforcer, agents_with_keys, valid_token):
        alice, bob = agents_with_keys
        enforcer.revoke_token(valid_token.token_id)
        assert enforcer.verify(bob, alice, valid_token) == AuthResult.REVOKED

    def test_denied_scope(self, enforcer, agents_with_keys):
        alice, bob = agents_with_keys
        token = enforcer.issue_token(alice, bob, ["dm:receive"], ttl_hours=24)
        assert enforcer.verify(bob, alice, token) == AuthResult.SCOPE_INSUFFICIENT

    def test_denied_key_mismatch(self, enforcer, agents_with_keys, valid_token):
        alice, bob = agents_with_keys
        tampered = AuthToken(
            token_id=valid_token.token_id,
            issuer=valid_token.issuer,
            subject=valid_token.subject,
            scope=valid_token.scope,
            issued_at=valid_token.issued_at,
            expires_at=valid_token.expires_at,
            signature="00" * 64,
            public_key=valid_token.public_key,
        )
        assert enforcer.verify(bob, alice, tampered) == AuthResult.KEY_MISMATCH
