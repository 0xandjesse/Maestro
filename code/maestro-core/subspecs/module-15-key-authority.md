# Module 15: Key Authority — Sub-spec
## Assigned to: Cactus Jack

### Interface Contract
```python
# nucleus/modules/key_authority/interface.py
from dataclasses import dataclass

@dataclass
class KeyPair:
    agent_id: str
    public_key: str
    private_key_encrypted: str
    created_at: int
    key_id: str

@dataclass
class SignedToken:
    token_id: str
    payload: dict
    signature: str
    signer_agent_id: str
    signer_public_key: str
    issued_at: int
    expires_at: int | None

@dataclass
class VerificationResult:
    valid: bool
    reason: str
    signer_agent_id: str | None

class KeyAuthority:
    def generate_keypair(self, agent_id: str) -> KeyPair: ...
    def get_public_key(self, agent_id: str) -> str | None: ...
    def rotate_keypair(self, agent_id: str) -> KeyPair: ...
    def sign(self, agent_id: str, payload: dict, bearer_token: str) -> SignedToken: ...
    def verify(self, token: SignedToken) -> VerificationResult: ...
    def issue_token(self, issuer_id: str, subject_id: str, scope: list[str], ttl_hours: int) -> SignedToken: ...
    def verify_issued_token(self, token_id: str) -> VerificationResult: ...
    def revoke_key(self, agent_id: str, key_id: str) -> bool: ...
    def is_revoked(self, key_id: str) -> bool: ...
```

### Critical Security Design
- Ed25519 key pairs
- Private keys encrypted at rest (AES-256-GCM)
- Key storage: `nucleus/data/keys/{agent_id}.enc`
- Revocation list: `nucleus/data/revoked_keys.json`
- Two-factor signing: encrypted key + bearer token

### Files to Create (absolute paths)
- `/home/andjesse/Projects/Maestro/nucleus/modules/key_authority/__init__.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/key_authority/interface.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/key_authority/authority.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/key_authority/schema.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/key_authority/test_authority.py`

### Dependencies
None — fully independent. Use Python stdlib only (cryptography library if available, fallback to hashlib+hmac).

### Success Criteria
- Generate Ed25519 keypairs
- Sign and verify tokens
- Encrypt/decrypt private keys
- Revocation list works
- Unit tests: generate, sign, verify, revoke, rotate
