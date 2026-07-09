"""
LOCR Token Attestation Layer — Credential Issuance via Maestro Token Primitive.

Consumes maestro.tokens.issue_token to produce signed attestation tokens
with the LOCR credential_attestation payload convention (§II.1.1 of LOCR-V2-COMPLETE.md).

Usage:
    from maestro.locr_attest import attest_credential

    token = attest_credential(
        wallet="0x1234...",
        uid="a3k9m2",
        bearer_id="agent-47",
        issuer_id="taskmaster",
        issuer_private_key_hex="<hex>",
        issuer_public_key_hex="<hex>",
        expiry=None,  # optional
    )
"""

from __future__ import annotations

from typing import Optional

from maestro.tokens import issue_token


def attest_credential(
    wallet: str,
    uid: str,
    bearer_id: str,
    issuer_id: str,
    issuer_private_key_hex: str,
    issuer_public_key_hex: str,
    issued_because: Optional[str] = None,
    evidence_url: Optional[str] = None,
    expiry: Optional[int] = None,
) -> dict:
    """Issue a LOCR credential attestation token.

    Builds the payload convention from LOCR-V2-COMPLETE.md §II.1.1 and
    delegates signing to the Maestro token primitive.

    Args:
        wallet: Agent's wallet address — identity anchor for credential possession
        uid: LOCR credential UID (canonical identifier, e.g. "a3k9m2")
        bearer_id: Agent ID this attestation is issued to
        issuer_id: Agent ID of the credential issuer (e.g. "taskmaster")
        issuer_private_key_hex: Issuer's Ed25519 private key (hex, 64 chars)
        issuer_public_key_hex: Issuer's Ed25519 public key (hex, 64 chars)
        issued_because: Human-readable reason (advisory only). e.g. "30x 5★ completions"
        evidence_url: URL to the issuer's verify endpoint for independent re-check.
            Defaults to None (evidence_url is advisory).
        expiry: Unix timestamp or None for permanent attestation.

    Returns:
        Signed Maestro token dict with payload.type = "credential_attestation"

    Raises:
        ValueError: If expiry is in the past (delegated to issue_token)
    """
    payload: dict = {
        "type": "credential_attestation",
        "credential_uid": uid,
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
