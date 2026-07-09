"""Authorization Verifier — file-backed implementation.

Uses Key Authority for Ed25519 signing/verification and Registry Manager
for agent lookups.  Tokens are persisted via TokenStore.

This is a Grammar module. It validates authorization artifacts —
signatures, tokens, identity claims. It answers "is this artifact valid?"
It does NOT answer "may this interaction occur?" — that's a policy question.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
import uuid
from pathlib import Path

from nucleus.modules.key_authority import FileKeyAuthority, SignedToken
from nucleus.modules.registry_manager import FileRegistryManager

from .interface import AuthorizationVerifier, AuthResult, AuthToken
from .token_store import TokenStore

log = logging.getLogger(__name__)


class FileAuthorizationVerifier(AuthorizationVerifier):
    """File-backed authorization artifact verifier.

    Parameters
    ----------
    key_authority : FileKeyAuthority
        Key authority for signing and verifying tokens.
    registry : FileRegistryManager
        Agent registry for looking up agents.
    tokens_dir : str
        Directory for per-token JSON files.
    revocation_path : str
        Path to the revocation list JSON file.
    """

    def __init__(
        self,
        key_authority: FileKeyAuthority,
        registry: FileRegistryManager,
        tokens_dir: str = "nucleus/data/dm_tokens",
        revocation_path: str = "nucleus/data/revoked_tokens.json",
    ) -> None:
        self._ka = key_authority
        self._registry = registry
        self._store = TokenStore(
            tokens_dir=tokens_dir,
            revocation_path=revocation_path,
        )

    # ── public API ─────────────────────────────────────────────────────

    def verify(
        self,
        sender_id: str,
        recipient_id: str,
        token: AuthToken | None = None,
    ) -> AuthResult:
        """Verify whether *token* is a valid authorization artifact."""
        if token is None:
            return AuthResult.NO_TOKEN

        # 1. Check revocation
        if self._store.is_revoked(token.token_id):
            return AuthResult.REVOKED

        # 2. Check expiry
        now_ms = int(time.time() * 1000)
        if token.expires_at > 0 and now_ms >= token.expires_at:
            return AuthResult.EXPIRED

        # 3. Verify signature
        valid, reason = self.verify_token(token)
        if not valid:
            return AuthResult.KEY_MISMATCH

        # 4. Bind token to sender — the subject must match the caller
        if token.subject != sender_id:
            return AuthResult.SUBJECT_MISMATCH

        # 5. Check scope — sender needs "dm:send"
        if "dm:send" not in token.scope:
            return AuthResult.SCOPE_INSUFFICIENT

        return AuthResult.VALID

    def issue_token(
        self,
        issuer_id: str,
        subject_id: str,
        scope: list[str],
        ttl_hours: int = 24,
    ) -> AuthToken:
        """Issue a new authorization token from *issuer_id* to *subject_id*."""
        now_ms = int(time.time() * 1000)
        expires_at = now_ms + (ttl_hours * 3600 * 1000)
        token_id = uuid.uuid4().hex[:16]

        # Get the issuer's public key
        public_key = self._ka.get_public_key(issuer_id)
        if public_key is None:
            raise ValueError(
                f"Issuer {issuer_id!r} has no key pair — generate one first"
            )

        # Build the payload to sign — this exact dict is what we verify later
        payload = {
            "token_id": token_id,
            "iss": issuer_id,
            "sub": subject_id,
            "scope": list(scope),
            "iat": now_ms,
            "exp": expires_at,
        }

        # Ensure the issuer has a signing token for signing
        bearer = self._ensure_signing_token(issuer_id)

        # Sign the payload directly with Key Authority
        signed = self._ka.sign(issuer_id, payload, bearer)

        auth_token = AuthToken(
            token_id=token_id,
            issuer=issuer_id,
            subject=subject_id,
            scope=list(scope),
            issued_at=now_ms,
            expires_at=expires_at,
            signature=signed.signature,
            public_key=public_key,
        )

        # Persist
        self._store.save_token(auth_token)

        return auth_token

    def revoke_token(self, token_id: str) -> bool:
        """Revoke *token_id*.

        Returns True if the token existed and was revoked.
        """
        if not self._store.token_exists(token_id):
            return False

        if self._store.is_revoked(token_id):
            return False  # already revoked

        self._store.add_revocation(token_id, reason="manual revocation")
        return True

    def verify_token(self, token: AuthToken) -> tuple[bool, str]:
        """Verify *token*'s signature, expiry, and revocation status.

        Returns (valid, reason).
        """
        # 1. Check revocation
        if self._store.is_revoked(token.token_id):
            return False, "Token has been revoked"

        # 2. Check expiry
        now_ms = int(time.time() * 1000)
        if token.expires_at > 0 and now_ms >= token.expires_at:
            return False, "Token has expired"

        # 3. Verify signature via Key Authority
        # Reconstruct the exact payload that was signed
        payload = {
            "token_id": token.token_id,
            "iss": token.issuer,
            "sub": token.subject,
            "scope": token.scope,
            "iat": token.issued_at,
            "exp": token.expires_at,
        }

        signed = SignedToken(
            token_id=token.token_id,
            payload=payload,
            signature=token.signature,
            signer_agent_id=token.issuer,
            signer_public_key=token.public_key,
            issued_at=token.issued_at,
            expires_at=token.expires_at,
        )

        result = self._ka.verify(signed)
        if not result.valid:
            return False, result.reason

        return True, "Token is valid"

    # ── internal helpers ───────────────────────────────────────────────

    def _ensure_signing_token(self, agent_id: str) -> str:
        """Ensure *agent_id* has a signing token for signing operations.

        Returns the plaintext signing token.
        """
        # Generate a fresh system signing token and register it
        new_token = secrets.token_hex(32)
        self._ka.setup_signing_token(agent_id, new_token)
        return new_token
