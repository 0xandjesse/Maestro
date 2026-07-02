"""Key Authority — Interface Contract.

Defines KeyPair, SignedToken, VerificationResult, and the
KeyAuthority abstract base class that all implementations must satisfy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class KeyPair:
    """A generated Ed25519 key pair with encrypted private key.

    Attributes
    ----------
    agent_id : str
        The agent this key pair belongs to.
    public_key : str
        Hex-encoded Ed25519 public key (64 hex chars).
    private_key_encrypted : str
        AES-256-GCM encrypted private key, base64-encoded.
    created_at : int
        Unix timestamp (milliseconds) when the key was generated.
    key_id : str
        Unique identifier for this key (first 16 chars of SHA-256 of public key).
    """

    agent_id: str
    public_key: str
    private_key_encrypted: str
    created_at: int
    key_id: str


@dataclass
class SignedToken:
    """A payload signed by an agent's private key.

    Attributes
    ----------
    token_id : str
        Unique identifier for this token.
    payload : dict
        The data being signed (arbitrary JSON-serializable dict).
    signature : str
        Ed25519 signature, hex-encoded (128 hex chars).
    signer_agent_id : str
        The agent that signed this token.
    signer_public_key : str
        The public key used to verify the signature (hex-encoded).
    issued_at : int
        Unix timestamp (milliseconds) when the token was issued.
    expires_at : int | None
        Unix timestamp (milliseconds) when the token expires, or None if no expiry.
    """

    token_id: str
    payload: dict
    signature: str
    signer_agent_id: str
    signer_public_key: str
    issued_at: int
    expires_at: int | None


@dataclass
class VerificationResult:
    """Outcome of a signature or token verification.

    Attributes
    ----------
    valid : bool
        True if the signature/token is valid.
    reason : str
        Human-readable explanation of the result.
    signer_agent_id : str | None
        The agent that signed the token (None if verification failed before
        the signer could be determined).
    """

    valid: bool
    reason: str
    signer_agent_id: str | None


class KeyAuthority(ABC):
    """Abstract interface for key generation, signing, and verification.

    Implementations must provide Ed25519 key pairs, AES-256-GCM encryption
    of private keys at rest, and a revocation list.
    """

    @abstractmethod
    def generate_keypair(self, agent_id: str) -> KeyPair:
        """Generate a new Ed25519 key pair for *agent_id*.

        The private key is encrypted at rest with AES-256-GCM before
        the KeyPair is returned.
        """
        ...

    @abstractmethod
    def get_public_key(self, agent_id: str) -> str | None:
        """Return the hex-encoded public key for *agent_id*, or None."""
        ...

    @abstractmethod
    def rotate_keypair(self, agent_id: str) -> KeyPair:
        """Generate a new key pair for *agent_id*, revoking the old one.

        The old key is added to the revocation list before the new key
        is generated.
        """
        ...

    @abstractmethod
    def sign(
        self, agent_id: str, payload: dict, bearer_token: str
    ) -> SignedToken:
        """Sign *payload* with *agent_id*'s private key.

        Requires *bearer_token* as a second factor — the encrypted private
        key is only decrypted if the bearer token is valid.
        """
        ...

    @abstractmethod
    def verify(self, token: SignedToken) -> VerificationResult:
        """Verify the Ed25519 signature on *token*.

        Checks signature validity, key revocation status, and token expiry.
        """
        ...

    @abstractmethod
    def issue_token(
        self,
        issuer_id: str,
        subject_id: str,
        scope: list[str],
        ttl_hours: int,
    ) -> SignedToken:
        """Issue a signed token from *issuer_id* to *subject_id*.

        The payload includes the subject, scope, and expiry derived from
        *ttl_hours*.
        """
        ...

    @abstractmethod
    def verify_issued_token(self, token_id: str) -> VerificationResult:
        """Verify a previously issued token by its *token_id*.

        Looks up the token in the issued-token store and verifies it.
        """
        ...

    @abstractmethod
    def revoke_key(self, agent_id: str, key_id: str) -> bool:
        """Add *key_id* to the revocation list for *agent_id*.

        Returns True if the key was not already revoked.
        """
        ...

    @abstractmethod
    def is_revoked(self, key_id: str) -> bool:
        """Return True if *key_id* is in the revocation list."""
        ...
