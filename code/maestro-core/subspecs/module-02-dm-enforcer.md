# Module 2: DM Enforcer — Sub-spec
## Assigned to: Cee-Lo

### Interface Contract
```python
# nucleus/modules/dm_enforcer/interface.py
from enum import Enum
from dataclasses import dataclass, field

class DMPolicyResult(Enum):
    ALLOWED = "allowed"
    DENIED_NO_TOKEN = "denied_no_token"
    DENIED_EXPIRED = "denied_expired"
    DENIED_REVOKED = "denied_revoked"
    DENIED_SCOPE = "denied_scope"
    DENIED_KEY_MISMATCH = "denied_key_mismatch"

@dataclass
class DMToken:
    token_id: str
    issuer: str                     # agentId of issuer
    subject: str                    # agentId of bearer
    scope: list[str]                # ["dm:send", "dm:receive"]
    issued_at: int                  # epoch ms
    expires_at: int                 # epoch ms
    signature: str                  # Ed25519 signature
    public_key: str                 # issuer's public key

class DMEnforcer:
    def check_policy(self, sender_id: str, recipient_id: str, token: DMToken | None = None) -> DMPolicyResult: ...
    def issue_token(self, issuer_id: str, subject_id: str, scope: list[str], ttl_hours: int = 24) -> DMToken: ...
    def revoke_token(self, token_id: str) -> bool: ...
    def verify_token(self, token: DMToken) -> tuple[bool, str]: ...  # (valid, reason)
```

### Key Behavior
- **check_policy:** Verify sender→recipient communication is allowed. Check token validity, expiry, scope, and revocation status.
- **issue_token:** Create a new DM token with scope, TTL, and signature. Store in `nucleus/data/dm_tokens/{token_id}.json`.
- **revoke_token:** Move token to revoked list. Returns True if token existed and was revoked.
- **verify_token:** Validate token signature, expiry, and revocation. Returns (valid, reason).
- **Token storage:** `nucleus/data/dm_tokens/{token_id}.json` — create directory if needed
- **Revocation list:** `nucleus/data/revoked_tokens.json` — append-only list of revoked token IDs
- **Scope checking:** Token must have "dm:send" scope for sender, "dm:receive" for recipient

### Files to Create (absolute paths)
- `/home/andjesse/Projects/Maestro/nucleus/modules/dm_enforcer/__init__.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/dm_enforcer/interface.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/dm_enforcer/enforcer.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/dm_enforcer/token_store.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/dm_enforcer/schema.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/dm_enforcer/test_enforcer.py`

### Dependencies
- Key Authority (M15) — built at `/home/andjesse/Projects/Maestro/nucleus/modules/key_authority/`. Import for signing/verification.
- Registry Manager (M4) — built at `/home/andjesse/Projects/Maestro/nucleus/modules/registry_manager/`. Import for agent lookup.

### Success Criteria
- check_policy allows valid token with correct scope
- check_policy denies expired token
- check_policy denies revoked token
- check_policy denies missing token
- issue_token creates valid token with correct fields
- revoke_token moves token to revoked list
- verify_token validates signature and expiry
- Unit tests: all policy results, token lifecycle, revocation, scope checking
