"""DM Enforcer — Interface Contract.

Defines DMPolicyResult, DMToken, and the DMEnforcer abstract base class
that all implementations must satisfy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class DMPolicyResult(Enum):
    """Outcome of a DM policy check."""

    ALLOWED = "allowed"
    DENIED_NO_TOKEN = "denied_no_token"
    DENIED_EXPIRED = "denied_expired"
    DENIED_REVOKED = "denied_revoked"
    DENIED_SCOPE = "denied_scope"
    DENIED_KEY_MISMATCH = "denied_key_mismatch"
    DENIED_SUBJECT_MISMATCH = "denied_subject_mismatch"


@dataclass
class DMToken:
    """A DM authorization token issued to an agent.

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


class DMEnforcer(ABC):
    """Abstract interface for DM policy enforcement and token management."""

    @abstractmethod
    def check_policy(
        self,
        sender_id: str,
        recipient_id: str,
        token: DMToken | None = None,
    ) -> DMPolicyResult:
        """Check whether *sender_id* may send a DM to *recipient_id*.

        If *token* is None, the result is DENIED_NO_TOKEN.
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
    ) -> DMToken:
        """Issue a new DM token from *issuer_id* to *subject_id*.

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
    def verify_token(self, token: DMToken) -> tuple[bool, str]:
        """Verify *token*'s signature, expiry, and revocation status.

        Returns (valid, reason).
        """
        ...
