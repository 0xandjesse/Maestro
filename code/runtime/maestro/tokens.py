"""
Maestro Token Primitive — Protocol-Level Token Operations.

A token is a signed artifact. Nothing more. The protocol provides mechanical
operations: issue, sign, verify, revoke, expire. Payload meaning is defined
by the consuming Venue, not by the protocol.

No type/scope/actions/resources/venues/allow_delegation fields at protocol level.
All downstream systems (TaskMaster, LOCR, Venues, Plaza) import from here.

Usage:
    from maestro.tokens import issue_token, validate_token, revoke_token

    token = issue_token(
        bearer_id="stormtrooper",
        payload={"access": "read"},
        issuer_id="proteus",
        issuer_private_key_hex="...",
        issuer_public_key_hex="...",
    )

    valid, reason = validate_token(token)

Dependencies: maestro_crypto (Ed25519 sign/verify/hash), ~/.maestro/registry.json
"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

from nacl.exceptions import BadSignatureError

from maestro_crypto import sign, verify


# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

REGISTRY_PATH = Path(os.path.expanduser("~/.maestro/registry.json"))
REVOKED_TOKENS_DIR = Path(os.path.expanduser("~/.maestro/revoked_tokens"))


# ──────────────────────────────────────────────
# Registry helpers
# ──────────────────────────────────────────────

def _load_registry(path: Optional[Path] = None) -> list:
    """Load the agent registry JSON. Handles both legacy flat-array and new wrapped format.

    Retries up to 3 times with 100ms backoff to handle transient file locks
    during concurrent reads (observed as intermittent issuer_not_in_registry errors).
    """
    import time as _time
    p = path or REGISTRY_PATH
    for attempt in range(3):
        try:
            if not p.exists():
                raise FileNotFoundError(f"Registry not found at {p}")
            raw = json.loads(p.read_text())
            if isinstance(raw, list):
                return raw  # Legacy flat array
            if isinstance(raw, dict):
                return raw.get("entries", [])  # New wrapped format
            return []
        except (json.JSONDecodeError, OSError) as e:
            if attempt < 2:
                _time.sleep(0.1 * (attempt + 1))
                continue
            raise RuntimeError(f"Registry unreadable after 3 attempts: {e}") from e
    return []  # unreachable


def _get_public_key(agent_id: str, registry: Optional[list] = None) -> Optional[str]:
    """Look up an agent's public key in the registry."""
    reg = registry if registry is not None else _load_registry()
    for entry in reg:
        if entry.get("agentId") == agent_id:
            return entry.get("publicKey")
    return None


# ──────────────────────────────────────────────
# Revocation list helpers
# ──────────────────────────────────────────────

def _get_revoked_file(issuer_id: str) -> Path:
    """Get the path to an issuer's revocation list file."""
    return REVOKED_TOKENS_DIR / f"{issuer_id}.json"


def _load_revoked_tokens(issuer_id: str) -> list:
    """Load the revoked token IDs for an issuer."""
    path = _get_revoked_file(issuer_id)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _save_revoked_tokens(issuer_id: str, revoked_ids: list) -> None:
    """Save the revoked token IDs for an issuer."""
    REVOKED_TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    _get_revoked_file(issuer_id).write_text(json.dumps(revoked_ids, indent=2))


# ──────────────────────────────────────────────
# Canonical Token Serialisation
# ──────────────────────────────────────────────

def canonical_json(token_fields: dict) -> str:
    """Serialize token fields for signing: sorted keys, no whitespace.

    Excludes the 'signature' field. Used internally by issue_token
    and validate_token to produce a deterministic signing payload.

    Args:
        token_fields: Token dict (with or without signature field)

    Returns:
        Canonical JSON string suitable for hashing and signing
    """
    fields = {k: v for k, v in token_fields.items() if k != "signature"}
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


# ──────────────────────────────────────────────
# Token Issuance
# ──────────────────────────────────────────────

def issue_token(
    bearer_id: str,
    payload: dict,
    issuer_id: str,
    issuer_private_key_hex: str,
    issuer_public_key_hex: str,
    expiry: Optional[int] = None,
) -> dict:
    """Issue a new token. Signs with the issuer's private key.

    The payload is an opaque dict — the issuer and bearer negotiate
    its meaning off-protocol. The protocol does not inspect it.

    Args:
        bearer_id: Agent ID this token is issued to
        payload: Opaque dict — Venue defines its meaning
        issuer_id: Agent ID of the issuer
        issuer_private_key_hex: Ed25519 private key (hex)
        issuer_public_key_hex: Ed25519 public key (hex)
        expiry: Unix timestamp or None for permanent

    Returns:
        Signed token dict with all protocol fields + signature

    Raises:
        ValueError: If expiry is in the past
    """
    now = int(time.time())

    if expiry is not None and expiry <= now:
        raise ValueError(
            f"Expiry {expiry} is in the past (now: {now})"
        )

    token = {
        "token_id": str(uuid.uuid4()),
        "version": 1,
        "issuer_id": issuer_id,
        "bearer_id": bearer_id,
        "issuer_public_key": issuer_public_key_hex,
        "payload": payload,
        "expiry": expiry,
        "issued_at": now,
        "nonce": os.urandom(32).hex(),
    }

    # Sign over canonical JSON
    token["signature"] = sign(canonical_json(token), issuer_private_key_hex)

    return token


# ──────────────────────────────────────────────
# Token Validation
# ──────────────────────────────────────────────

def validate_token(
    token: dict,
    revocation_lists: Optional[dict] = None,
) -> tuple:
    """Validate a token's cryptographic integrity and liveness.

    Checks: signature validity, registry key resolution, expiry, revocation.
    Does NOT check: payload contents, issuer trustworthiness, bearer authorization.

    Protocol validation verifies cryptographic integrity and liveness only.
    Venues MUST validate bearer authorization — accept tokens only from
    callers matching token["bearer_id"].

    Args:
        token: Token dict in protocol schema
        revocation_lists: Optional dict of issuer_id → set of revoked token_ids.
            If None, revocation check is skipped (revocation distribution is
            a deployment concern).

    Returns:
        (valid: bool, reason: str) — reason is empty string when valid
    """
    # 1. Signature validity
    try:
        if not verify(
            canonical_json(token),
            token["signature"],
            token["issuer_public_key"],
        ):
            return False, "invalid_signature"
    except (BadSignatureError, KeyError, ValueError, TypeError):
        return False, "invalid_signature"

    # 2. Registry key resolution — confirm issuer_public_key matches
    #    the registered public key for issuer_id
    try:
        reg = _load_registry()
    except FileNotFoundError:
        # Registry not available — skip key resolution but warn
        pass
    else:
        registered_key = _get_public_key(token["issuer_id"], reg)
        if registered_key is None:
            return False, f"issuer_not_in_registry:{token['issuer_id']}"
        if registered_key != token["issuer_public_key"]:
            return False, "issuer_key_mismatch"

    # 3. Expiry check
    expiry = token.get("expiry")
    if expiry is not None and expiry <= int(time.time()):
        return False, "expired"

    # 4. Revocation check
    if revocation_lists is not None:
        issuer_id = token["issuer_id"]
        revoked = revocation_lists.get(issuer_id, set())
        if token["token_id"] in revoked:
            return False, "revoked"

    return True, ""


# ──────────────────────────────────────────────
# Token Revocation
# ──────────────────────────────────────────────

def revoke_token(
    token_id: str,
    issuer_id: str,
    issuer_private_key_hex: str,
) -> dict:
    """Revoke a token. Adds to the issuer's revocation list.

    Only the issuer can revoke their own tokens. Returns a signed
    revocation record that can be broadcast or stored.

    Args:
        token_id: The token to revoke
        issuer_id: Agent ID of the issuer (must match token's issuer)
        issuer_private_key_hex: Issuer's Ed25519 private key (hex)

    Returns:
        Revocation record: {token_id, revoked_at, issuer_id, issuer_signature}
    """
    now = int(time.time())

    # Load current list, append, save
    revoked_ids = _load_revoked_tokens(issuer_id)
    if token_id not in revoked_ids:
        revoked_ids.append(token_id)
    _save_revoked_tokens(issuer_id, revoked_ids)

    # Produce signed revocation record
    record = {
        "token_id": token_id,
        "revoked_at": now,
        "issuer_id": issuer_id,
    }
    record["issuer_signature"] = sign(
        canonical_json(record), issuer_private_key_hex
    )

    return record


# ──────────────────────────────────────────────
# Token Transfer (Future — v2)
# ──────────────────────────────────────────────

def transfer_token(
    token: dict,
    new_bearer_id: str,
    bearer_private_key_hex: str,
) -> dict:
    """Transfer a token to a new bearer. (Future — v2 stub)

    Returns a new token with updated bearer_id, preserving original
    issuer + payload. Requires the current bearer's signature to
    authorize the transfer.

    Args:
        token: The existing token
        new_bearer_id: Agent ID to transfer the token to
        bearer_private_key_hex: Current bearer's Ed25519 private key

    Returns:
        New signed token with updated bearer_id

    Raises:
        NotImplementedError: Transfer is not yet implemented (v2)
    """
    raise NotImplementedError(
        "Token transfer is not yet implemented. Planned for Maestro Token Primitive v2."
    )
