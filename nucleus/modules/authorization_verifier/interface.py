"""Authorization Verifier — Interface Contract.

Defines AuthResult, AuthToken, and the AuthorizationVerifier abstract base class
that all implementations must satisfy.

This module validates authorization artifacts — signatures, tokens, identity claims.
It answers "is this artifact valid?" It does NOT answer "may this interaction occur?"
Policy evaluation belongs to the Policy layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class AuthResult(Enum):
    """Outcome of an authorization artifact verification."""

    VALID = "valid"
    NO_TOKEN = "no_token"
    EXPIRED = "expired"
    REVOKED = "revoked"
    SCOPE_INSUFFICIENT = "scope_insufficient"
    KEY_MISMATCH = "key_mismatch"
    SUBJECT_MISMATCH = "subject_mismatch"


@dataclass
class AuthToken:
    """An authorization token issued to an agent.

    Attributes
    ----------
    token_id : str
        Unique identifier for this token.
    issuer : str
        agentId of the issuing agent.
    subject : str
        agentId of the bearer (the agent authorized to use this token).
    scope : list[str]
        Permissions granted, e.g. ["dm:send", "dm:receive"].
    issued_at : int
        Epoch milliseconds when the token was issued.
    expires_at : int
        Epoch milliseconds when the token expires.
    signature : str
        Ed25519 signature over the token payload (hex-encoded).
    public_key : str
        Issuer's Ed25519 public key (hex-encoded, 64 chars).
    """

    token_id: str
    issuer: str
    subject: str
    scope: list[str] = field(default_factory=list)
    issued_at: int = 0
    expires_at: int = 0
    signature: str = ""
    public_key: str = ""


class AuthorizationVerifier(ABC):
    """Abstract interface for authorization artifact verification and token management.

    This is a Grammar module. It validates authorization artifacts —
    signatures, tokens, identity claims. It answers "is this artifact valid?"
    It does NOT answer "may this interaction occur?" — that's a policy question
    that belongs to the Policy layer.
    """

    @abstractmethod
    def verify(
        self,
        sender_id: str,
        recipient_id: str,
        token: AuthToken | None = None,
    ) -> AuthResult:
        """Verify whether *token* is a valid authorization artifact.

        If *token* is None, the result is NO_TOKEN.
        Otherwise the token is validated for expiry, revocation, scope,
        and key integrity.
        """
        ...

    @abstractmethod
    def issue_token(
        self,
        issuer_id: str,
        subject_id: str,
        scope: list[str],
        ttl_hours: int = 24,
    ) -> AuthToken:
        """Issue a new authorization token from *issuer_id* to *subject_id*.

        The token is signed with the issuer's Ed25519 key and persisted
        to the token store.
        """
        ...

    @abstractmethod
    def revoke_token(self, token_id: str) -> bool:
        """Revoke *token_id*.

        Returns True if the token existed and was revoked, False if it
        was already revoked or never existed.
        """
        ...

    @abstractmethod
    def verify_token(self, token: AuthToken) -> tuple[bool, str]:
        """Verify *token*'s signature, expiry, and revocation status.

        Returns (valid, reason).
        """
        ...
