"""
LOCR Token Verification Layer — Local + Remote Credential Verification.

Consumes maestro.tokens.validate_token for cryptographic integrity checks
and adds LOCR-specific checks: payload type, issuer trust, credential UID.

Provides three verification paths:
  1. verify_token — local (token signature + LOCR checks)
  2. verify_endpoint — remote (HTTP GET to issuer's verify endpoint)
  3. verify_credential — unified (tries token first, falls back to endpoint)

Usage:
    from maestro.locr_verify import verify_token, verify_endpoint, verify_credential

    valid, reason = verify_token(token, required_uid="a3k9m2", trusted_issuers=["taskmaster"])

    valid, reason = verify_endpoint(
        "https://api.taskmaster.tech/verify", wallet="0x...", uid="a3k9m2"
    )

    valid, reason = verify_credential(
        token=token,
        verify_endpoint="https://api.taskmaster.tech/verify",
        wallet="0x...",
        uid="a3k9m2",
        trusted_issuers=["taskmaster"],
    )
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from typing import Optional

from maestro.tokens import validate_token


# ──────────────────────────────────────────────
# Local Token Verification
# ──────────────────────────────────────────────

def verify_token(
    token: dict,
    required_uid: str,
    trusted_issuers: list,
) -> tuple:
    """Verify an attestation token locally (no external HTTP call).

    Checks in order:
      1. Maestro token cryptographic validity (signature, expiry, registry key)
      2. issuer_id is in trusted_issuers
      3. payload.type == "credential_attestation"
      4. payload.credential_uid == required_uid

    Args:
        token: Maestro token dict with credential_attestation payload
        required_uid: The credential UID that must match (exact)
        trusted_issuers: List of issuer_ids that this verifier trusts

    Returns:
        (valid: bool, reason: str) — reason is empty string when valid
    """
    # 1. Protocol-level token validation
    valid, reason = validate_token(token)
    if not valid:
        return False, reason

    # 2. Issuer trust
    if token["issuer_id"] not in trusted_issuers:
        return False, f"untrusted_issuer:{token['issuer_id']}"

    # 3. Payload type check
    payload = token.get("payload") or {}
    if payload.get("type") != "credential_attestation":
        return False, "not_a_credential_attestation"

    # 4. Credential UID match
    if payload.get("credential_uid") != required_uid:
        return False, "wrong_credential"

    return True, ""


# ──────────────────────────────────────────────
# Remote Endpoint Verification
# ──────────────────────────────────────────────

def verify_endpoint(
    verify_endpoint: str,
    wallet: str,
    uid: str,
    timeout: float = 3.0,
) -> tuple:
    """Verify credential via the issuer's remote verification endpoint.

    Follows LOCR-V2-COMPLETE.md §II.2 protocol:
      GET {verify_endpoint}?wallet={wallet}&uid={uid}
      → {"valid": true} or {"valid": false}

    Timeout: 3 seconds (configurable).
    Retry: 1 retry with 100–250ms random backoff on network/timeout errors only.
    Total budget: ≤ 5 seconds.
    Non-200 responses are definitive failures (no retry).

    Args:
        verify_endpoint: Base URL of the issuer's LOCR verification endpoint
            (e.g. "https://api.taskmaster.tech/verify")
        wallet: Agent's wallet address
        uid: LOCR credential UID to verify
        timeout: HTTP request timeout in seconds (default: 3.0)

    Returns:
        (valid: bool, reason: str)
    """
    url = f"{verify_endpoint}?wallet={wallet}&uid={uid}"

    for attempt in range(2):  # first attempt + 1 retry
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    # Non-200 is a definitive failure — no retry
                    return False, "verification_unavailable"

                body = json.loads(resp.read().decode("utf-8"))
                valid_result = body.get("valid", False)
                if valid_result:
                    return True, ""
                return False, "credential_not_held"

        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
            if attempt == 0:
                # Retry with 100–250ms random backoff on network errors only
                backoff_ms = random.randint(100, 250)
                time.sleep(backoff_ms / 1000.0)
                continue
            return False, "verification_unavailable"

    return False, "verification_unavailable"


# ──────────────────────────────────────────────
# Unified Verification (Token → Endpoint Fallback)
# ──────────────────────────────────────────────

def verify_credential(
    token: Optional[dict] = None,
    endpoint: Optional[str] = None,
    wallet: Optional[str] = None,
    uid: Optional[str] = None,
    trusted_issuers: Optional[list] = None,
) -> tuple:
    """Unified credential verification — tries token first, falls back to endpoint.

    Strategy:
      - If token is provided and not expired: use verify_token (local, fast)
      - If token is None, expired, or local verification fails:
        use verify_endpoint (remote, slower)
      - Falls back to endpoint when token validation fails for any reason

    Args:
        token: Maestro attestation token (optional). If None, falls back to endpoint.
        verify_endpoint: Remote verification endpoint URL. Required for endpoint fallback.
        wallet: Agent's wallet address. Required for endpoint fallback.
        uid: Required credential UID. Required for both paths.
        trusted_issuers: List of trusted issuer_ids. Required for token verification.

    Returns:
        (valid: bool, reason: str) — reason is empty string when valid
    """
    # Try token-based verification first
    if token is not None and trusted_issuers is not None and uid is not None:
        valid, reason = verify_token(token, required_uid=uid, trusted_issuers=trusted_issuers)
        if valid:
            return True, ""
        # If the failure is NOT an untrusted issuer or wrong credential,
        # we might still try the endpoint for a live re-check.
        # But if the issuer is explicitly untrusted, don't fall through.
        if reason.startswith("untrusted_issuer"):
            return False, reason
        if reason == "wrong_credential":
            return False, reason
        # For expired/invalid_signature/revoked/not_a_credential_attestation:
        # fall through to endpoint if available.

    # Fall back to endpoint verification
    if endpoint is not None and wallet is not None and uid is not None:
        return verify_endpoint(endpoint, wallet=wallet, uid=uid)

    # Not enough information for either path
    return False, "insufficient_verification_params"
