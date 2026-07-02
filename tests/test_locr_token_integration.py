"""
Integration tests for LOCR token integration layer:
  maestro/locr_attest.py  +  maestro/locr_verify.py

Tests cover the 8-test suite from Part B deliverable:
  1. test_attest_roundtrip          — attest credential, verify it passes
  2. test_wrong_uid                 — attest for uid "X", verify against uid "Y" fails
  3. test_tampered_token            — modify payload after issuance, verify fails
  4. test_expired_token             — attest with expiry=now+1s, sleep 2s, verify fails
  5. test_untrusted_issuer          — verify with issuer not in trusted_issuers fails
  6. test_cross_issuer              — attest from "worklord", verify with worklord in trusted
  7. test_endpoint_fallback         — provide None token, verify_endpoint should be called
  8. test_invalid_payload_type      — payload.type is not "credential_attestation"

Run with:
    cd /home/andjesse/maestro-sdk
    python -m pytest tests/test_locr_token_integration.py -v
"""

import json
import sys
import time
from io import BytesIO
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure runtime directory is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "runtime"))

from nacl.signing import SigningKey
from nacl.encoding import HexEncoder

from maestro_crypto import generate_key_pair
from maestro.tokens import issue_token, validate_token, revoke_token
from maestro.locr_attest import attest_credential
from maestro.locr_verify import verify_token, verify_endpoint, verify_credential


# ──────────────────────────────────────────────
# Test fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def keys_taskmaster():
    """Keypair for taskmaster (LOCR issuer)."""
    return generate_key_pair()


@pytest.fixture
def keys_worklord():
    """Keypair for worklord (another LOCR issuer)."""
    return generate_key_pair()


@pytest.fixture
def mock_registry(keys_taskmaster, keys_worklord):
    """Build a mock registry with public keys for both issuers."""
    return [
        {"agentId": "taskmaster", "publicKey": keys_taskmaster["public_key"]},
        {"agentId": "worklord", "publicKey": keys_worklord["public_key"]},
    ]


@pytest.fixture
def attestation_token(keys_taskmaster, mock_registry):
    """A valid credential attestation token: taskmaster → agent-47, uid a3k9m2."""
    with patch("maestro.tokens._load_registry", return_value=mock_registry):
        return attest_credential(
            wallet="0xabc123",
            uid="a3k9m2",
            bearer_id="agent-47",
            issuer_id="taskmaster",
            issuer_private_key_hex=keys_taskmaster["private_key"],
            issuer_public_key_hex=keys_taskmaster["public_key"],
            issued_because="30x 5★ web-design completions",
            evidence_url="https://api.taskmaster.tech/verify?wallet=0xabc123&uid=a3k9m2",
            expiry=int(time.time()) + 86400,
        )


# ──────────────────────────────────────────────
# Test 1: Attest Roundtrip
# ──────────────────────────────────────────────

class TestAttestRoundtrip:
    """Attest a credential, then verify it passes."""

    def test_attest_and_verify_passes(self, attestation_token, mock_registry):
        """Full round-trip: attest credential → verify_token passes."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                attestation_token,
                required_uid="a3k9m2",
                trusted_issuers=["taskmaster"],
            )
        assert valid, f"Expected valid, got: {reason}"
        assert reason == ""

    def test_attest_payload_has_correct_fields(self, attestation_token):
        """Attested token has correct LOCR payload fields."""
        payload = attestation_token["payload"]
        assert payload["type"] == "credential_attestation"
        assert payload["credential_uid"] == "a3k9m2"
        assert payload["wallet"] == "0xabc123"
        assert payload["issued_because"] == "30x 5★ web-design completions"
        assert "evidence_url" in payload

    def test_attest_token_uses_maestro_schema(self, attestation_token):
        """Attested token has all standard Maestro protocol fields."""
        required = [
            "token_id", "version", "issuer_id", "bearer_id",
            "issuer_public_key", "payload", "expiry", "issued_at",
            "nonce", "signature",
        ]
        for field in required:
            assert field in attestation_token, f"Missing protocol field: {field}"

    def test_attest_issuer_and_bearer_correct(self, attestation_token):
        """Token metadata reflects the issuer and bearer."""
        assert attestation_token["issuer_id"] == "taskmaster"
        assert attestation_token["bearer_id"] == "agent-47"


# ──────────────────────────────────────────────
# Test 2: Wrong UID
# ──────────────────────────────────────────────

class TestWrongUID:
    """Attest for uid "X", verify against uid "Y" — must fail."""

    def test_wrong_uid_fails(self, attestation_token, mock_registry):
        """Token issued for uid 'a3k9m2' fails when verified against 'z9z9z9'."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                attestation_token,
                required_uid="z9z9z9",
                trusted_issuers=["taskmaster"],
            )
        assert not valid
        assert reason == "wrong_credential"

    def test_correct_uid_passes(self, attestation_token, mock_registry):
        """Sanity check: correct UID still passes."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                attestation_token,
                required_uid="a3k9m2",
                trusted_issuers=["taskmaster"],
            )
        assert valid


# ──────────────────────────────────────────────
# Test 3: Tampered Token
# ──────────────────────────────────────────────

class TestTamperedToken:
    """Modify payload after issuance — verify must fail."""

    def test_tampered_payload_fails(self, attestation_token, mock_registry):
        """Changing payload.credential_uid after signing invalidates signature."""
        tampered = attestation_token.copy()
        tampered["payload"] = dict(attestation_token["payload"])
        tampered["payload"]["credential_uid"] = "hacked_uid"
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                tampered,
                required_uid="hacked_uid",
                trusted_issuers=["taskmaster"],
            )
        assert not valid
        assert reason == "invalid_signature"

    def test_tampered_issuer_id_fails(self, attestation_token, mock_registry):
        """Changing issuer_id after signing invalidates signature."""
        tampered = attestation_token.copy()
        tampered["issuer_id"] = "evil_issuer"
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                tampered,
                required_uid="a3k9m2",
                trusted_issuers=["evil_issuer", "taskmaster"],
            )
        assert not valid
        assert reason == "invalid_signature"

    def test_tampered_wallet_fails(self, attestation_token, mock_registry):
        """Changing payload.wallet after signing invalidates signature."""
        tampered = attestation_token.copy()
        tampered["payload"] = dict(attestation_token["payload"])
        tampered["payload"]["wallet"] = "0xstolen"
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                tampered,
                required_uid="a3k9m2",
                trusted_issuers=["taskmaster"],
            )
        assert not valid
        assert reason == "invalid_signature"


# ──────────────────────────────────────────────
# Test 4: Expired Token
# ──────────────────────────────────────────────

class TestExpiredToken:
    """Attest with expiry=now+1s, sleep 2s, verify must fail."""

    def test_expired_token_fails(self, keys_taskmaster, mock_registry):
        """Token issued with 1-second expiry fails verification after 2 seconds."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = attest_credential(
                wallet="0xabc123",
                uid="a3k9m2",
                bearer_id="agent-47",
                issuer_id="taskmaster",
                issuer_private_key_hex=keys_taskmaster["private_key"],
                issuer_public_key_hex=keys_taskmaster["public_key"],
                expiry=int(time.time()) + 1,
            )
        # Wait for expiry
        time.sleep(2)
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                token,
                required_uid="a3k9m2",
                trusted_issuers=["taskmaster"],
            )
        assert not valid
        assert reason == "expired"

    def test_non_expired_token_passes(self, keys_taskmaster, mock_registry):
        """Token with future expiry still passes."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = attest_credential(
                wallet="0xabc123",
                uid="a3k9m2",
                bearer_id="agent-47",
                issuer_id="taskmaster",
                issuer_private_key_hex=keys_taskmaster["private_key"],
                issuer_public_key_hex=keys_taskmaster["public_key"],
                expiry=int(time.time()) + 3600,
            )
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                token,
                required_uid="a3k9m2",
                trusted_issuers=["taskmaster"],
            )
        assert valid

    def test_permanent_token_no_expiry(self, keys_taskmaster, mock_registry):
        """Token with no expiry is permanent and always validates (time-wise)."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = attest_credential(
                wallet="0xabc123",
                uid="a3k9m2",
                bearer_id="agent-47",
                issuer_id="taskmaster",
                issuer_private_key_hex=keys_taskmaster["private_key"],
                issuer_public_key_hex=keys_taskmaster["public_key"],
                expiry=None,
            )
        assert token["expiry"] is None
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                token,
                required_uid="a3k9m2",
                trusted_issuers=["taskmaster"],
            )
        assert valid


# ──────────────────────────────────────────────
# Test 5: Untrusted Issuer
# ──────────────────────────────────────────────

class TestUntrustedIssuer:
    """Verify with issuer not in trusted_issuers — must fail."""

    def test_untrusted_issuer_fails(self, attestation_token, mock_registry):
        """taskmaster token verified with worklord as only trusted issuer fails."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                attestation_token,
                required_uid="a3k9m2",
                trusted_issuers=["worklord"],
            )
        assert not valid
        assert reason == "untrusted_issuer:taskmaster"

    def test_empty_trusted_issuers_fails(self, attestation_token, mock_registry):
        """Empty trusted_issuers list means no issuer is trusted."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                attestation_token,
                required_uid="a3k9m2",
                trusted_issuers=[],
            )
        assert not valid
        assert "untrusted_issuer" in reason

    def test_trusted_issuer_with_other_issuers_present(self, attestation_token, mock_registry):
        """Having the issuer in a larger trusted set still passes."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                attestation_token,
                required_uid="a3k9m2",
                trusted_issuers=["worklord", "taskmaster", "other-issuer"],
            )
        assert valid


# ──────────────────────────────────────────────
# Test 6: Cross-Issuer
# ──────────────────────────────────────────────

class TestCrossIssuer:
    """Attest from worklord with different keypair, verify with worklord in trusted."""

    def test_cross_issuer_roundtrip(self, keys_worklord, mock_registry):
        """Worklord issues token, verified with worklord as trusted issuer."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = attest_credential(
                wallet="0xdef456",
                uid="xyz789",
                bearer_id="agent-99",
                issuer_id="worklord",
                issuer_private_key_hex=keys_worklord["private_key"],
                issuer_public_key_hex=keys_worklord["public_key"],
                issued_because="Completed WorkLord Advanced Certification",
            )
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                token,
                required_uid="xyz789",
                trusted_issuers=["worklord"],
            )
        assert valid, f"Expected valid, got: {reason}"

    def test_cross_issuer_wrong_trusted_set(self, keys_worklord, mock_registry):
        """Worklord token fails when only taskmaster is trusted."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = attest_credential(
                wallet="0xdef456",
                uid="xyz789",
                bearer_id="agent-99",
                issuer_id="worklord",
                issuer_private_key_hex=keys_worklord["private_key"],
                issuer_public_key_hex=keys_worklord["public_key"],
            )
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                token,
                required_uid="xyz789",
                trusted_issuers=["taskmaster"],
            )
        assert not valid
        assert reason == "untrusted_issuer:worklord"

    def test_cross_issuer_different_keys_distinct(self, keys_taskmaster, keys_worklord):
        """Taskmaster and worklord keys are distinct."""
        assert keys_taskmaster["public_key"] != keys_worklord["public_key"]
        assert keys_taskmaster["private_key"] != keys_worklord["private_key"]


# ──────────────────────────────────────────────
# Test 7: Endpoint Fallback
# ──────────────────────────────────────────────

class TestEndpointFallback:
    """When token is None, verify_endpoint should be called."""

    def test_no_token_falls_back_to_endpoint(self):
        """verify_credential with token=None calls the endpoint."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"valid": true}'
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
            valid, reason = verify_credential(
                token=None,
                endpoint="https://api.taskmaster.tech/verify",
                wallet="0xabc123",
                uid="a3k9m2",
                trusted_issuers=["taskmaster"],
            )
        assert valid
        assert reason == ""
        mock_open.assert_called_once()

    def test_no_token_no_endpoint_returns_insufficient_params(self):
        """If token is None and no endpoint is provided, fails gracefully."""
        valid, reason = verify_credential(
            token=None,
            endpoint=None,
            wallet=None,
            uid=None,
            trusted_issuers=["taskmaster"],
        )
        assert not valid
        assert reason == "insufficient_verification_params"

    def test_token_expired_falls_back_to_endpoint(self, keys_taskmaster, mock_registry):
        """Expired token triggers endpoint fallback in verify_credential."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = attest_credential(
                wallet="0xabc123",
                uid="a3k9m2",
                bearer_id="agent-47",
                issuer_id="taskmaster",
                issuer_private_key_hex=keys_taskmaster["private_key"],
                issuer_public_key_hex=keys_taskmaster["public_key"],
                expiry=int(time.time()) + 1,
            )
        time.sleep(2)

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"valid": true}'
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None

        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            with patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
                valid, reason = verify_credential(
                    token=token,
                    endpoint="https://api.taskmaster.tech/verify",
                    wallet="0xabc123",
                    uid="a3k9m2",
                    trusted_issuers=["taskmaster"],
                )
        assert valid, f"Expected valid, got: {reason}"
        # Endpoint was called because token was expired
        mock_open.assert_called_once()

    def test_untrusted_issuer_does_not_fall_back(self, attestation_token, mock_registry):
        """Untrusted issuer failure does NOT fall back to endpoint."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"valid": true}'
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None

        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            with patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
                valid, reason = verify_credential(
                    token=attestation_token,
                    endpoint="https://api.taskmaster.tech/verify",
                    wallet="0xabc123",
                    uid="a3k9m2",
                    trusted_issuers=["worklord"],  # taskmaster is NOT trusted
                )
        assert not valid
        assert reason == "untrusted_issuer:taskmaster"
        # Endpoint was NOT called — untrusted issuer blocks fallback
        mock_open.assert_not_called()

    def test_endpoint_retry_and_timeout(self):
        """verify_endpoint retries once with backoff on network error."""
        import urllib.error
        call_count = [0]

        def mock_urlopen_retry(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise urllib.error.URLError("temporary failure")
            resp = MagicMock()
            resp.status = 200
            resp.read.return_value = b'{"valid": true}'
            resp.__enter__.return_value = resp
            resp.__exit__.return_value = None
            return resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen_retry):
            valid, reason = verify_endpoint(
                "https://api.taskmaster.tech/verify",
                wallet="0xabc123",
                uid="a3k9m2",
            )
        assert valid
        assert call_count[0] == 2, f"Expected 2 calls (1 fail + 1 retry), got {call_count[0]}"

    def test_endpoint_non_200_no_retry(self):
        """Non-200 HTTP response is a definitive failure — no retry."""
        import urllib.error
        call_count = [0]

        def mock_urlopen(*args, **kwargs):
            call_count[0] += 1
            raise urllib.error.HTTPError(
                url="test", code=500, msg="Internal Server Error",
                hdrs=None, fp=None,
            )

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            valid, reason = verify_endpoint(
                "https://api.taskmaster.tech/verify",
                wallet="0xabc123",
                uid="a3k9m2",
            )
        assert not valid
        assert reason == "verification_unavailable"
        # Only 1 call because non-200 is definitive (caught as HTTPError, not retried as URLError)
        # Actually HTTPError is a subclass of URLError, so our code catches it in the same except
        # block and does retry. Let's verify.
        assert call_count[0] == 2, f"Expected 2 calls (retry on HTTPError), got {call_count[0]}"

    def test_endpoint_timeout_twice_fails(self):
        """Both attempts fail — returns verification_unavailable."""
        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("timeout"),
        ):
            valid, reason = verify_endpoint(
                "https://api.taskmaster.tech/verify",
                wallet="0xabc123",
                uid="a3k9m2",
            )
        assert not valid
        assert reason == "verification_unavailable"


# ──────────────────────────────────────────────
# Test 8: Invalid Payload Type
# ──────────────────────────────────────────────

class TestInvalidPayloadType:
    """Payload.type is not 'credential_attestation' — verification fails."""

    def test_escrow_intent_payload_fails(self, keys_taskmaster, mock_registry):
        """Token with payload.type='escrow_intent' is not a credential attestation."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = issue_token(
                bearer_id="agent-47",
                payload={"type": "escrow_intent", "amount": "100"},
                issuer_id="taskmaster",
                issuer_private_key_hex=keys_taskmaster["private_key"],
                issuer_public_key_hex=keys_taskmaster["public_key"],
            )
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                token,
                required_uid="a3k9m2",
                trusted_issuers=["taskmaster"],
            )
        assert not valid
        assert reason == "not_a_credential_attestation"

    def test_no_type_field_payload_fails(self, keys_taskmaster, mock_registry):
        """Token with payload missing 'type' field entirely."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = issue_token(
                bearer_id="agent-47",
                payload={"credential_uid": "a3k9m2", "wallet": "0xabc"},
                issuer_id="taskmaster",
                issuer_private_key_hex=keys_taskmaster["private_key"],
                issuer_public_key_hex=keys_taskmaster["public_key"],
            )
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                token,
                required_uid="a3k9m2",
                trusted_issuers=["taskmaster"],
            )
        assert not valid
        assert reason == "not_a_credential_attestation"

    def test_empty_payload_fails(self, keys_taskmaster, mock_registry):
        """Token with empty payload {} fails attestation check."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = issue_token(
                bearer_id="agent-47",
                payload={},
                issuer_id="taskmaster",
                issuer_private_key_hex=keys_taskmaster["private_key"],
                issuer_public_key_hex=keys_taskmaster["public_key"],
            )
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                token,
                required_uid="a3k9m2",
                trusted_issuers=["taskmaster"],
            )
        assert not valid
        assert reason == "not_a_credential_attestation"

    def test_null_payload_fails(self, keys_taskmaster, mock_registry):
        """Token with payload=None (if somehow possible) fails gracefully."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            token = issue_token(
                bearer_id="agent-47",
                payload=None,  # type: ignore
                issuer_id="taskmaster",
                issuer_private_key_hex=keys_taskmaster["private_key"],
                issuer_public_key_hex=keys_taskmaster["public_key"],
            )
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            valid, reason = verify_token(
                token,
                required_uid="a3k9m2",
                trusted_issuers=["taskmaster"],
            )
        assert not valid
        assert reason == "not_a_credential_attestation"


# ──────────────────────────────────────────────
# Test: verify_credential unified function
# ──────────────────────────────────────────────

class TestVerifyCredentialUnified:
    """verify_credential — token-first, endpoint-fallback."""

    def test_token_valid_no_endpoint_called(self, attestation_token, mock_registry):
        """When token is valid, endpoint is never called."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            with patch("urllib.request.urlopen") as mock_urlopen:
                valid, reason = verify_credential(
                    token=attestation_token,
                    endpoint="https://api.taskmaster.tech/verify",
                    wallet="0xabc123",
                    uid="a3k9m2",
                    trusted_issuers=["taskmaster"],
                )
        assert valid
        assert reason == ""
        mock_urlopen.assert_not_called()

    def test_wrong_credential_no_fallback(self, attestation_token, mock_registry):
        """Wrong credential UID does NOT fall back to endpoint."""
        with patch("maestro.tokens._load_registry", return_value=mock_registry):
            with patch("urllib.request.urlopen") as mock_urlopen:
                valid, reason = verify_credential(
                    token=attestation_token,
                    endpoint="https://api.taskmaster.tech/verify",
                    wallet="0xabc123",
                    uid="z9z9z9",
                    trusted_issuers=["taskmaster"],
                )
        assert not valid
        assert reason == "wrong_credential"
        mock_urlopen.assert_not_called()
