"""
LOCR v2 — Credential Attestation via Maestro Token Primitive.

LOCR (Lightweight Open Credentials Registry) consumes the Maestro token
primitive to issue, verify, and consume credential attestation tokens.

This module defines:
  1. Payload conventions for credential_attestation tokens
  2. Local verification (token signature + issuer trust + credential UID)
  3. Remote verification (LOCR endpoint fallback)

LOCR is a consumer of the token primitive. It does NOT define its own token
format. All tokens are Maestro tokens with LOCR payload conventions.

Usage:
    from maestro.locr import (
        issue_credential_attestation,
        verify_attestation,
        verify_attestation_local,
        verify_attestation_remote,
    )

    token = issue_credential_attestation(
        bearer_id="agent-47",
        credential_uid="a3k9m2",
        wallet="0x...",
        issuer_id="taskmaster",
        issuer_private_key_hex="...",
        issuer_public_key_hex="...",
    )

    valid, reason = verify_attestation_local(
        token,
        trusted_issuers=["taskmaster"],
        required_credential_uid="a3k9m2",
    )

Dependencies: maestro.tokens, maestro_crypto
"""

import time
import urllib.request
import urllib.error
from typing import Optional

from maestro.tokens import (
    issue_token,
    validate_token,
    revoke_token,
    canonical_json,
    _load_revoked_tokens,
)


# ──────────────────────────────────────────────
# Credential Attestation Issuance
# ──────────────────────────────────────────────

def issue_credential_attestation(
    bearer_id: str,
    credential_uid: str,
    wallet: str,
    issuer_id: str,
    issuer_private_key_hex: str,
    issuer_public_key_hex: str,
    issued_because: Optional[str] = None,
    evidence_url: Optional[str] = None,
    expiry: Optional[int] = None,
) -> dict:
    """Issue a credential attestation token.

    Builds the LOCR payload convention and delegates signing to the
    Maestro token primitive (maestro.tokens.issue_token).

    Args:
        bearer_id: Agent ID this attestation is issued to
        credential_uid: LOCR credential UID (canonical identifier)
        wallet: Agent's wallet address — identity anchor for credential possession
        issuer_id: Agent ID of the credential issuer
        issuer_private_key_hex: Issuer's Ed25519 private key (hex)
        issuer_public_key_hex: Issuer's Ed25519 public key (hex)
        issued_because: Human-readable reason (advisory only, no security role)
        evidence_url: URL to verification endpoint for independent re-check
        expiry: Unix timestamp or None for permanent

    Returns:
        Signed Maestro token with payload.type = "credential_attestation"

    Raises:
        ValueError: If required payload fields are missing
    """
    payload = {
        "type": "credential_attestation",
        "credential_uid": credential_uid,
        "wallet": wallet,
    }

    if issued_because is not None:
        payload["issued_because"] = issued_because
    if evidence_url is not None:
        payload["evidence_url"] = evidence_url

    return issue_token(
        bearer_id=bearer_id,
        payload=payload,
        issuer_id=issuer_id,
        issuer_private_key_hex=issuer_private_key_hex,
        issuer_public_key_hex=issuer_public_key_hex,
        expiry=expiry,
    )


# ──────────────────────────────────────────────
# Local Verification (Token-Only)
# ──────────────────────────────────────────────

def verify_attestation_local(
    token: dict,
    trusted_issuers: Optional[list] = None,
    required_credential_uid: Optional[str] = None,
    revocation_lists: Optional[dict] = None,
) -> tuple:
    """Verify an attestation token locally (no external HTTP call).

    Checks in order:
      1. Maestro token cryptographic validity (signature, expiry, revocation)
      2. Payload type is "credential_attestation"
      3. Issuer is in the trusted set (if provided)
      4. Credential UID matches the required UID (if provided)

    This is the fast path — the issuer already signed the attestation, so
    no remote call is needed if the verifier trusts the issuer and has
    the issuer's public key cached.

    Args:
        token: Maestro token dict with credential_attestation payload
        trusted_issuers: List of issuer_ids that this verifier trusts.
            If None or empty, issuer trust check is skipped.
        required_credential_uid: If set, the token's credential_uid must
            match exactly. If None, UID check is skipped.
        revocation_lists: Optional dict of issuer_id → set of revoked
            token_ids. Passed through to validate_token.

    Returns:
        (valid: bool, reason: str) — reason is empty string when valid
    """
    # 1. Protocol-level token validation
    valid, reason = validate_token(token, revocation_lists=revocation_lists)
    if not valid:
        return False, reason

    # 2. Payload type check
    payload = token.get("payload", {})
    if payload.get("type") != "credential_attestation":
        return False, "not_a_credential_attestation"

    # 3. Issuer trust
    if trusted_issuers:
        if token["issuer_id"] not in trusted_issuers:
            return False, f"untrusted_issuer:{token['issuer_id']}"

    # 4. Credential UID match
    if required_credential_uid is not None:
        if payload.get("credential_uid") != required_credential_uid:
            return False, "wrong_credential"

    return True, ""


# ──────────────────────────────────────────────
# Remote Verification (Endpoint Fallback)
# ──────────────────────────────────────────────

def verify_attestation_remote(
    verify_endpoint: str,
    wallet: str,
    credential_uid: str,
    timeout: float = 3.0,
) -> tuple:
    """Verify credential attestation via the issuer's remote endpoint.

    Follows the LOCR verification protocol (LOCR-V2-COMPLETE.md §Verification):
      GET {verify_endpoint}?wallet={address}&uid={uid}
      → {"valid": true} or {"valid": false}

    Timeout: 3 seconds. Retry: 1 retry with 100–250ms random backoff.
    Total budget: ≤ 5 seconds.
    On any failure (timeout, network error, non-200): treat as
    {"valid": false, "reason": "verification_unavailable"}.

    This is the slow path — use when the verifier doesn't have the issuer's
    public key cached, the token has expired and a live re-check is needed,
    or revocation is suspected and the revocation list may be stale.

    Args:
        verify_endpoint: Base URL of the issuer's LOCR verification endpoint
            (e.g. "https://api.taskmaster.tech/verify")
        wallet: Agent's wallet address
        credential_uid: LOCR credential UID to verify
        timeout: HTTP request timeout in seconds (default: 3.0)

    Returns:
        (valid: bool, reason: str)
    """
    import random

    url = f"{verify_endpoint}?wallet={wallet}&uid={credential_uid}"

    for attempt in range(2):  # first attempt + 1 retry
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    # Non-200 is a definitive failure — no retry
                    return False, "verification_unavailable"

                import json
                body = json.loads(resp.read().decode("utf-8"))
                valid = body.get("valid", False)
                if valid:
                    return True, ""
                return False, "credential_not_held"

        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
            if attempt == 0:
                # Retry with 100–250ms random backoff
                backoff_ms = random.randint(100, 250)
                time.sleep(backoff_ms / 1000.0)
                continue
            return False, "verification_unavailable"

    return False, "verification_unavailable"


# ──────────────────────────────────────────────
# Combined Verification (Local → Remote Fallback)
# ──────────────────────────────────────────────

def verify_attestation(
    token: dict,
    trusted_issuers: Optional[list] = None,
    required_credential_uid: Optional[str] = None,
    revocation_lists: Optional[dict] = None,
    issuer_verify_endpoint: Optional[str] = None,
    wallet: Optional[str] = None,
) -> tuple:
    """Verify a credential attestation — local first, remote fallback.

    Tries local verification first (fast path, no HTTP). Falls back to
    remote verification if:
      - The token's signature can't be verified locally (issuer key unavailable)
      - The token has expired and a live re-check is needed
      - Revocation is suspected

    Args:
        token: Maestro token dict with credential_attestation payload
        trusted_issuers: Issuers this verifier trusts
        required_credential_uid: Required credential UID (exact match)
        revocation_lists: Dict of issuer_id → set of revoked token_ids
        issuer_verify_endpoint: Fallback endpoint URL for remote verification.
            Required if remote fallback is desired.
        wallet: Wallet address for remote verification. If not provided,
            extracted from token's payload.wallet.

    Returns:
        (valid: bool, reason: str)
    """
    # Try local first
    valid, reason = verify_attestation_local(
        token,
        trusted_issuers=trusted_issuers,
        required_credential_uid=required_credential_uid,
        revocation_lists=revocation_lists,
    )

    if valid:
        return True, ""

    # Determine if we should attempt remote fallback
    fallback_reasons = {
        "invalid_signature",
        "issuer_not_in_registry",
        "issuer_key_mismatch",
        "expired",
        "revoked",
    }

    if reason in fallback_reasons or reason.startswith("issuer_not_in_registry"):
        if issuer_verify_endpoint is not None:
            # Use wallet from token payload if not explicitly provided
            wallet_addr = wallet or token.get("payload", {}).get("wallet")
            if wallet_addr is None:
                return False, f"{reason}_no_wallet_for_remote"
            cred_uid = token.get("payload", {}).get("credential_uid")
            if cred_uid is None:
                return False, f"{reason}_no_credential_uid"
            return verify_attestation_remote(
                issuer_verify_endpoint, wallet_addr, cred_uid
            )

    return False, reason


# ──────────────────────────────────────────────
# Revocation Helpers
# ──────────────────────────────────────────────

def revoke_credential_attestation(
    token_id: str,
    issuer_id: str,
    issuer_private_key_hex: str,
) -> dict:
    """Revoke a credential attestation token.

    Delegates to maestro.tokens.revoke_token. Only the issuer can revoke.

    Args:
        token_id: The token to revoke
        issuer_id: Agent ID of the issuer
        issuer_private_key_hex: Issuer's Ed25519 private key (hex)

    Returns:
        Signed revocation record
    """
    return revoke_token(token_id, issuer_id, issuer_private_key_hex)
