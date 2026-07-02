"""Key Authority — Ed25519 key management, signing, and verification.

Exports
-------
* ``KeyPair`` — generated key pair (public + encrypted private)
* ``SignedToken`` — signed payload with verification metadata
* ``VerificationResult`` — outcome of signature verification
* ``KeyAuthority`` — abstract interface
* ``FileKeyAuthority`` — file-backed implementation
"""

from .interface import KeyAuthority, KeyPair, SignedToken, VerificationResult
from .authority import FileKeyAuthority
from .schema import validate_key_storage, validate_revocation_list

__all__ = [
    "FileKeyAuthority",
    "KeyAuthority",
    "KeyPair",
    "SignedToken",
    "VerificationResult",
    "validate_key_storage",
    "validate_revocation_list",
]
