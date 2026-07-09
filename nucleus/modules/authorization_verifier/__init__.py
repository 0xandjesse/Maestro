"""Authorization Verifier — authorization artifact verification and token management.

Exports
-------
* ``AuthResult`` — enum of verification outcomes
* ``AuthToken`` — dataclass for an authorization token
* ``AuthorizationVerifier`` — abstract interface
* ``FileAuthorizationVerifier`` — file-backed implementation
* ``validate_token_entry``, ``validate_revocation_list`` — schema validators
"""

from .interface import AuthorizationVerifier, AuthResult, AuthToken
from .enforcer import FileAuthorizationVerifier
from .schema import validate_revocation_list, validate_token_entry

__all__ = [
    "AuthorizationVerifier",
    "AuthResult",
    "AuthToken",
    "FileAuthorizationVerifier",
    "validate_revocation_list",
    "validate_token_entry",
]
