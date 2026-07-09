"""
Integration tests for maestro/tokens.py — Maestro Token Primitive.

Tests cover the 6 integration tests from SPEC_MAESTRO_TOKEN_PRIMITIVE.md §9:
  1. Issue/Validate round-trip
  2. Expiry enforcement
  3. Revocation
  4. Signature tampering
  5. Payload opacity (protocol is payload-agnostic)
  6. Bearer mismatch (protocol passes; Venue MUST check)

Run with:
    cd /home/andjesse/maestro-sdk/runtime
    python -m pytest tests/test_token_primitive.py -v
"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure runtime directory is on sys.path for maestro_crypto and maestro.tokens import
sys.path.insert(0, str(Path(__file__).parent.parent / "runtime"))

from nacl.signing import SigningKey
from nacl.encoding import HexEncoder

from maestro_crypto import generate_key_pair, sign as crypto_sign, verify as crypto_verify
from maestro.tokens import (
    canonical_json,
    issue_token,
    revoke_token,
    validate_token,
    transfer_token,
)


# ──────────────────────────────────────────────
# Test fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def keys_lexicon():
    """Generate a keypair for lexicon."""
    return generate_key_pair()


@pytest.fixture
def keys_proteus():
    """Generate a keypair for proteus."""
    return generate_key_pair()


@pytest.fixture
def mock_registry(keys_lexicon, keys_proteus):
    """Build a mock registry with public keys."""
    return [
        {"agentId": "lexicon", "publicKey": keys_lexicon["public_key"]},
        {"agentId": "proteus", "publicKey": keys_proteus["public_key"]},
    ]


@pytest.fixture
def basic_token(keys_lexicon, mock_registry):
    """A basic token: lexicon → proteus, payload: {"access": "read"}"""
    with patch("maestro.tokens._load_registry", return_value=mock_registry):
        return issue_token(
            bearer_id="proteus",
            payload={"access": "read"},
            issuer_id="lexicon",
            issuer_private_key_hex=keys_lexicon["private_key"],
            issuer_public_key_hex=keys_lexicon["public_key"],
        )


# ──────────────────────────────────────────────
# Test 1: Issue/Validate Round-Trip
# ──────────────────────────────────────────────

class TestIssueValidateRoundTrip:
    """§9 Test 1: Issue token and validate — passes. Tamper payload — fails."""

    def test_issue_and_validate_passes(self, basic_token, keys_lexicon, mock_registry):
        """Issued token validates successfully."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = validate_token(basic_token)
        assert valid, f"Expected valid, got: {reason}"
        assert reason == ""

    def test_tampered_payload_fails_validation(self, basic_token, mock_registry):
        """Tampering with payload invalidates signature."""
        tampered = basic_token.copy()
        tampered["payload"] = {"access": "write"}
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = validate_token(tampered)
        assert not valid
        assert reason == "invalid_signature"

    def test_token_has_all_protocol_fields(self, basic_token):
        """Issued token contains all protocol-level fields."""
        required_fields = [
            "token_id", "version", "issuer_id", "bearer_id",
            "issuer_public_key", "payload", "expiry", "issued_at",
            "nonce", "signature",
        ]
        for field in required_fields:
            assert field in basic_token, f"Missing field: {field}"

    def test_token_version_is_one(self, basic_token):
        """Token version is 1."""
        assert basic_token["version"] == 1


# ──────────────────────────────────────────────
# Test 2: Expiry Enforcement
# ──────────────────────────────────────────────

class TestExpiryEnforcement:
    """§9 Test 2: Token with past expiry fails validation with 'expired'."""

    def test_token_with_future_expiry_validates(self, keys_lexicon, mock_registry):
        """Token with future expiry passes."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = issue_token(
                bearer_id="proteus",
                payload={"task": "test"},
                issuer_id="lexicon",
                issuer_private_key_hex=keys_lexicon["private_key"],
                issuer_public_key_hex=keys_lexicon["public_key"],
                expiry=int(time.time()) + 3600,
            )
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = validate_token(token)
        assert valid, f"Expected valid, got: {reason}"

    def test_token_with_past_expiry_fails(self, keys_lexicon, mock_registry):
        """Token that expires, then time passes, fails validation."""
        very_soon = int(time.time()) + 1
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = issue_token(
                bearer_id="proteus",
                payload={"task": "test"},
                issuer_id="lexicon",
                issuer_private_key_hex=keys_lexicon["private_key"],
                issuer_public_key_hex=keys_lexicon["public_key"],
                expiry=very_soon,
            )
        # Wait for the token to expire
        time.sleep(1.1)
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = validate_token(token)
        assert not valid
        assert reason == "expired"

    def test_null_expiry_passes(self, keys_lexicon, mock_registry):
        """Token with expiry=None passes (permanent token)."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = issue_token(
                bearer_id="proteus",
                payload={"permanent": True},
                issuer_id="lexicon",
                issuer_private_key_hex=keys_lexicon["private_key"],
                issuer_public_key_hex=keys_lexicon["public_key"],
                expiry=None,
            )
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = validate_token(token)
        assert valid, f"Expected valid, got: {reason}"


# ──────────────────────────────────────────────
# Test 3: Revocation
# ──────────────────────────────────────────────

class TestRevocation:
    """§9 Test 3: Revoked token fails validation with 'revoked'."""

    def test_revoked_token_fails_validation(self, keys_lexicon, mock_registry):
        """After revocation, validation fails."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = issue_token(
                bearer_id="proteus",
                payload={"task": "revoke_me"},
                issuer_id="lexicon",
                issuer_private_key_hex=keys_lexicon["private_key"],
                issuer_public_key_hex=keys_lexicon["public_key"],
            )

        # Validate before revoke — should pass
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = validate_token(token)
        assert valid, f"Expected valid before revoke, got: {reason}"

        # Revoke
        revoke_token(
            token["token_id"],
            issuer_id="lexicon",
            issuer_private_key_hex=keys_lexicon["private_key"],
        )

        # Validate after revoke — should fail
        revoked_set = {token["token_id"]}
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = validate_token(
                token, revocation_lists={"lexicon": revoked_set}
            )
        assert not valid
        assert "revoked" == reason

    def test_revoke_returns_signed_record(self, keys_lexicon, mock_registry):
        """Revoke returns a properly signed revocation record."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = issue_token(
                bearer_id="proteus",
                payload={"task": "test"},
                issuer_id="lexicon",
                issuer_private_key_hex=keys_lexicon["private_key"],
                issuer_public_key_hex=keys_lexicon["public_key"],
            )

        record = revoke_token(
            token["token_id"],
            issuer_id="lexicon",
            issuer_private_key_hex=keys_lexicon["private_key"],
        )

        assert record["token_id"] == token["token_id"]
        assert record["issuer_id"] == "lexicon"
        assert "revoked_at" in record
        assert "issuer_signature" in record

        # Signature should verify
        signed = crypto_verify(
            canonical_json({
                "token_id": record["token_id"],
                "revoked_at": record["revoked_at"],
                "issuer_id": record["issuer_id"],
            }),
            record["issuer_signature"],
            keys_lexicon["public_key"],
        )
        assert signed, "Revocation record signature should verify"


# ──────────────────────────────────────────────
# Test 4: Signature Tampering
# ──────────────────────────────────────────────

class TestSignatureTampering:
    """§9 Test 4: Modifying bearer_id invalidates signature."""

    def test_tampered_bearer_id_fails(self, basic_token, mock_registry):
        """Changing bearer_id after signing invalidates the signature."""
        tampered = basic_token.copy()
        tampered["bearer_id"] = "stormtrooper"
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = validate_token(tampered)
        assert not valid
        assert reason == "invalid_signature"

    def test_tampered_issuer_id_fails(self, basic_token, mock_registry):
        """Changing issuer_id after signing invalidates the signature."""
        tampered = basic_token.copy()
        tampered["issuer_id"] = "proteus"
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = validate_token(tampered)
        assert not valid
        assert reason == "invalid_signature"

    def test_tampered_token_id_fails(self, basic_token, mock_registry):
        """Changing token_id after signing invalidates the signature."""
        tampered = basic_token.copy()
        tampered["token_id"] = "fake-token-id"
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = validate_token(tampered)
        assert not valid
        assert reason == "invalid_signature"


# ──────────────────────────────────────────────
# Test 5: Payload Opacity
# ──────────────────────────────────────────────

class TestPayloadOpacity:
    """§9 Test 5: Protocol is payload-agnostic. Any payload structure is valid."""

    def test_custom_venue_payload_validates(self, keys_lexicon, mock_registry):
        """Token with arbitrary payload fields validates — protocol is opaque."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = issue_token(
                bearer_id="proteus",
                payload={"custom_venue_field": "anything", "nested": {"deep": True}},
                issuer_id="lexicon",
                issuer_private_key_hex=keys_lexicon["private_key"],
                issuer_public_key_hex=keys_lexicon["public_key"],
            )
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = validate_token(token)
        assert valid, f"Expected valid, got: {reason}"

    def test_empty_payload_validates(self, keys_lexicon, mock_registry):
        """Token with empty payload {} validates."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = issue_token(
                bearer_id="proteus",
                payload={},
                issuer_id="lexicon",
                issuer_private_key_hex=keys_lexicon["private_key"],
                issuer_public_key_hex=keys_lexicon["public_key"],
            )
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = validate_token(token)
        assert valid, f"Expected valid, got: {reason}"

    def test_no_type_field_at_protocol_level(self, basic_token):
        """Token has no 'type' field — payload semantics are Venue-level."""
        assert "type" not in basic_token
        # Payload is opaque — even if it contains 'type', the protocol doesn't care
        assert "payload" in basic_token


# ──────────────────────────────────────────────
# Test 6: Bearer Mismatch (Venue-Level)
# ──────────────────────────────────────────────

class TestBearerMismatch:
    """§9 Test 6: Protocol validation PASSES on bearer mismatch.
    Bearer authorization is a Venue concern — the protocol verifies
    cryptographic integrity only. Venues MUST check token["bearer_id"]
    against the presenting agent."""

    def test_protocol_passes_bearer_mismatch(self, basic_token, mock_registry):
        """Token validates even when bearer_id != caller_id.
        This is CORRECT protocol behaviour — bearer binding is the Venue's job."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = validate_token(basic_token)
        assert valid, f"Expected valid, got: {reason}"
        # The protocol does NOT check who is presenting the token.
        # Venues MUST do: if token["bearer_id"] != presenting_agent: reject

    def test_token_bearer_id_is_set(self, basic_token):
        """Token has a bearer_id that Venues can check."""
        assert basic_token["bearer_id"] == "proteus"


# ──────────────────────────────────────────────
# Test: Canonical JSON
# ──────────────────────────────────────────────

class TestCanonicalJSON:
    """Canonical JSON serialization for deterministic signing."""

    def test_excludes_signature(self, basic_token):
        """canonical_json excludes the signature field."""
        canonical = canonical_json(basic_token)
        parsed = json.loads(canonical)
        assert "signature" not in parsed

    def test_deterministic(self, basic_token):
        """Same token produces identical output on repeated calls."""
        a = canonical_json(basic_token)
        b = canonical_json(basic_token)
        assert a == b

    def test_sorted_keys(self, basic_token):
        """Output has sorted keys."""
        parsed = json.loads(canonical_json(basic_token))
        keys = list(parsed.keys())
        assert keys == sorted(keys)


# ──────────────────────────────────────────────
# Test: Registry Key Mismatch
# ──────────────────────────────────────────────

class TestRegistryKeyResolution:
    """Registry key resolution ensures issuer_public_key matches registry."""

    def test_issuer_not_in_registry_fails(self, basic_token):
        """Token from unknown issuer fails validation."""
        empty_registry = []
        with patch("maestro.tokens._load_registry", return_value=empty_registry):
            valid, reason = validate_token(basic_token)
        assert not valid
        assert "issuer_not_in_registry" in reason

    def test_key_mismatch_fails(self, basic_token):
        """Token whose public key differs from registry entry fails."""
        mismatched_registry = [
            {"agentId": "lexicon", "publicKey": "deadbeef" * 4},
        ]
        with patch("maestro.tokens._load_registry", return_value=mismatched_registry):
            valid, reason = validate_token(basic_token)
        assert not valid
        assert reason == "issuer_key_mismatch"


# ──────────────────────────────────────────────
# Test: transfer_token stub
# ──────────────────────────────────────────────

class TestTransferToken:
    """transfer_token is a v2 stub — raises NotImplementedError."""

    def test_transfer_raises_not_implemented(self, basic_token, keys_proteus):
        """Calling transfer_token raises NotImplementedError."""
        with pytest.raises(NotImplementedError, match="not yet implemented"):
            transfer_token(
                basic_token,
                new_bearer_id="stormtrooper",
                bearer_private_key_hex=keys_proteus["private_key"],
            )


# ──────────────────────────────────────────────
# Test: issue_token with past expiry rejects
# ──────────────────────────────────────────────

class TestIssueTokenEdgeCases:
    """Edge cases for token issuance."""

    def test_issue_with_past_expiry_raises(self, keys_lexicon, mock_registry):
        """Issuing a token with expiry in the past raises ValueError."""
        past = int(time.time()) - 3600
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            with pytest.raises(ValueError, match="in the past"):
                issue_token(
                    bearer_id="proteus",
                    payload={},
                    issuer_id="lexicon",
                    issuer_private_key_hex=keys_lexicon["private_key"],
                    issuer_public_key_hex=keys_lexicon["public_key"],
                    expiry=past,
                )
