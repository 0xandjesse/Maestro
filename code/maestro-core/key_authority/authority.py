"""Key Authority — Ed25519 key management, signing, and verification.

Implements the KeyAuthority interface with:
* Ed25519 key pair generation (via cryptography.hazmat)
* AES-256-GCM encryption of private keys at rest
* Two-factor signing (encrypted key + bearer token)
* Key revocation list
* Issued token tracking

Storage layout
--------------
* Key storage:      ``nucleus/data/keys/{agent_id}.enc``
* Revocation list:  ``nucleus/data/revoked_keys.json``
* Bearer tokens:    ``nucleus/data/bearer_tokens.json``
* Issued tokens:    ``nucleus/data/issued_tokens.json``
* Master key:       ``nucleus/data/.master_key`` (auto-generated on first use)
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .interface import KeyAuthority, KeyPair, SignedToken, VerificationResult
from .schema import validate_key_storage, validate_revocation_list

log = logging.getLogger(__name__)

# ── constants ──────────────────────────────────────────────────────────

MASTER_KEY_LENGTH = 32  # AES-256
NONCE_LENGTH = 12  # AES-GCM standard nonce
SALT_LENGTH = 16
HKDF_INFO = b"nucleus-key-authority-v1"


class FileKeyAuthority(KeyAuthority):
    """File-backed key authority with Ed25519 + AES-256-GCM.

    Private keys are encrypted at rest with a master key derived from
    a stored secret.  Signing requires both the encrypted key and a
    valid bearer token (two-factor).
    """

    def __init__(
        self,
        keys_dir: str = "nucleus/data/keys",
        revocation_path: str = "nucleus/data/revoked_keys.json",
        bearer_tokens_path: str = "nucleus/data/bearer_tokens.json",
        issued_tokens_path: str = "nucleus/data/issued_tokens.json",
        master_key_path: str = "nucleus/data/.master_key",
    ) -> None:
        self._keys_dir = Path(keys_dir).resolve()
        self._keys_dir.mkdir(parents=True, exist_ok=True)

        self._revocation_path = Path(revocation_path).resolve()
        self._revocation_path.parent.mkdir(parents=True, exist_ok=True)

        self._bearer_tokens_path = Path(bearer_tokens_path).resolve()
        self._bearer_tokens_path.parent.mkdir(parents=True, exist_ok=True)

        self._issued_tokens_path = Path(issued_tokens_path).resolve()
        self._issued_tokens_path.parent.mkdir(parents=True, exist_ok=True)

        self._master_key_path = Path(master_key_path).resolve()
        self._master_key_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()

        # Load or generate the master key
        self._master_key = self._load_or_create_master_key()

    # ── public API ─────────────────────────────────────────────────────

    def generate_keypair(self, agent_id: str) -> KeyPair:
        """Generate a new Ed25519 key pair for *agent_id*."""
        if not agent_id or not isinstance(agent_id, str):
            raise ValueError("agent_id must be a non-empty string")

        # Generate Ed25519 key
        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        # Serialize
        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

        public_key_hex = public_bytes.hex()
        key_id = hashlib.sha256(public_bytes).hexdigest()[:16]
        created_at = int(time.time() * 1000)

        # Encrypt private key with master key
        nonce = secrets.token_bytes(NONCE_LENGTH)
        aesgcm = AESGCM(self._master_key)
        encrypted = aesgcm.encrypt(nonce, private_bytes, None)
        private_key_encrypted = base64.b64encode(nonce + encrypted).decode()

        keypair = KeyPair(
            agent_id=agent_id,
            public_key=public_key_hex,
            private_key_encrypted=private_key_encrypted,
            created_at=created_at,
            key_id=key_id,
        )

        # Persist
        self._save_key_entry(agent_id, keypair)

        return keypair

    def get_public_key(self, agent_id: str) -> str | None:
        """Return the hex-encoded public key for *agent_id*, or None."""
        entry = self._load_key_entry(agent_id)
        if entry is None:
            return None
        return entry.get("public_key")

    def rotate_keypair(self, agent_id: str) -> KeyPair:
        """Generate a new key pair, revoking the old one."""
        old_entry = self._load_key_entry(agent_id)
        if old_entry is not None:
            old_key_id = old_entry.get("key_id")
            if old_key_id:
                self.revoke_key(agent_id, old_key_id)

        return self.generate_keypair(agent_id)

    def sign(
        self, agent_id: str, payload: dict, bearer_token: str
    ) -> SignedToken:
        """Sign *payload* with *agent_id*'s private key.

        Requires a valid *bearer_token* as the second factor.
        """
        # Verify bearer token
        if not self._verify_bearer_token(agent_id, bearer_token):
            raise PermissionError(
                f"Invalid bearer token for agent {agent_id!r}"
            )

        # Load and decrypt the private key
        entry = self._load_key_entry(agent_id)
        if entry is None:
            raise ValueError(f"No key pair found for agent {agent_id!r}")

        # Check revocation
        key_id = entry.get("key_id", "")
        if self.is_revoked(key_id):
            raise PermissionError(
                f"Key {key_id} for agent {agent_id!r} has been revoked"
            )

        private_key = self._decrypt_private_key(
            entry["private_key_encrypted"]
        )

        # Serialize payload deterministically
        payload_bytes = json.dumps(payload, sort_keys=True).encode()

        # Sign
        signature = private_key.sign(payload_bytes)
        signature_hex = signature.hex()

        token_id = hashlib.sha256(
            f"{agent_id}:{signature_hex}:{time.time()}".encode()
        ).hexdigest()[:16]

        return SignedToken(
            token_id=token_id,
            payload=payload,
            signature=signature_hex,
            signer_agent_id=agent_id,
            signer_public_key=entry["public_key"],
            issued_at=int(time.time() * 1000),
            expires_at=None,
        )

    def verify(self, token: SignedToken) -> VerificationResult:
        """Verify the Ed25519 signature on *token*."""
        # Check revocation
        key_id = hashlib.sha256(
            bytes.fromhex(token.signer_public_key)
        ).hexdigest()[:16]

        if self.is_revoked(key_id):
            return VerificationResult(
                valid=False,
                reason=f"Signer key {key_id} has been revoked",
                signer_agent_id=token.signer_agent_id,
            )

        # Check expiry
        if token.expires_at is not None:
            now_ms = int(time.time() * 1000)
            if now_ms >= token.expires_at:
                return VerificationResult(
                    valid=False,
                    reason="Token has expired",
                    signer_agent_id=token.signer_agent_id,
                )

        # Verify signature
        try:
            public_key = ed25519.Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(token.signer_public_key)
            )
            payload_bytes = json.dumps(
                token.payload, sort_keys=True
            ).encode()
            signature_bytes = bytes.fromhex(token.signature)
            public_key.verify(signature_bytes, payload_bytes)
            return VerificationResult(
                valid=True,
                reason="Signature verified",
                signer_agent_id=token.signer_agent_id,
            )
        except Exception as exc:
            return VerificationResult(
                valid=False,
                reason=f"Signature verification failed: {exc}",
                signer_agent_id=token.signer_agent_id,
            )

    def issue_token(
        self,
        issuer_id: str,
        subject_id: str,
        scope: list[str],
        ttl_hours: int,
    ) -> SignedToken:
        """Issue a signed token from *issuer_id* to *subject_id*."""
        now_ms = int(time.time() * 1000)
        expires_at = now_ms + (ttl_hours * 3600 * 1000)

        payload = {
            "iss": issuer_id,
            "sub": subject_id,
            "scope": scope,
            "iat": now_ms,
            "exp": expires_at,
            "jti": uuid.uuid4().hex[:16],
        }

        # The issuer signs with their own key — but we need a bearer token.
        # For internal issuance, we use a system bearer token.
        system_token = self._get_or_create_system_token(issuer_id)
        signed = self.sign(issuer_id, payload, system_token)

        # Store the issued token
        self._store_issued_token(signed)

        return signed

    def verify_issued_token(self, token_id: str) -> VerificationResult:
        """Verify a previously issued token by its *token_id*."""
        issued = self._load_issued_tokens()
        for entry in issued:
            if entry.get("token_id") == token_id:
                # Reconstruct a SignedToken and verify
                token = SignedToken(
                    token_id=entry["token_id"],
                    payload=entry["payload"],
                    signature=entry["signature"],
                    signer_agent_id=entry["signer_agent_id"],
                    signer_public_key=entry["signer_public_key"],
                    issued_at=entry["issued_at"],
                    expires_at=entry.get("expires_at"),
                )
                return self.verify(token)

        return VerificationResult(
            valid=False,
            reason=f"Token {token_id!r} not found in issued token store",
            signer_agent_id=None,
        )

    def revoke_key(self, agent_id: str, key_id: str) -> bool:
        """Add *key_id* to the revocation list."""
        if self.is_revoked(key_id):
            return False

        revocations = self._load_revocations()
        revocations.append({
            "key_id": key_id,
            "agent_id": agent_id,
            "revoked_at": int(time.time() * 1000),
            "reason": "manual revocation",
        })
        self._save_revocations(revocations)
        return True

    def is_revoked(self, key_id: str) -> bool:
        """Return True if *key_id* is in the revocation list."""
        revocations = self._load_revocations()
        return any(r.get("key_id") == key_id for r in revocations)

    # ── bearer token management ───────────────────────────────────────

    def setup_bearer_token(self, agent_id: str, token: str) -> None:
        """Register a bearer token for *agent_id*.

        The token is stored as a SHA-256 hash; the plaintext is never persisted.
        """
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        tokens = self._load_bearer_tokens()
        tokens[agent_id] = token_hash
        self._save_bearer_tokens(tokens)

    def _verify_bearer_token(self, agent_id: str, token: str) -> bool:
        """Check that *token* matches the stored hash for *agent_id*."""
        tokens = self._load_bearer_tokens()
        stored_hash = tokens.get(agent_id)
        if stored_hash is None:
            return False
        return hashlib.sha256(token.encode()).hexdigest() == stored_hash

    def _get_or_create_system_token(self, agent_id: str) -> str:
        """Get or create a system bearer token for internal operations."""
        tokens = self._load_bearer_tokens()
        if agent_id in tokens:
            # We can't recover the plaintext — generate a new one
            # and update.  In practice, system tokens are set up once.
            pass
        # Generate a new system token
        new_token = secrets.token_hex(32)
        self.setup_bearer_token(agent_id, new_token)
        return new_token

    # ── master key management ──────────────────────────────────────────

    def _load_or_create_master_key(self) -> bytes:
        """Load the master key from disk, or generate a new one."""
        if self._master_key_path.exists():
            raw = self._master_key_path.read_bytes()
            if len(raw) == MASTER_KEY_LENGTH:
                return raw
            log.warning(
                "Master key has wrong length (%d), regenerating", len(raw)
            )

        # Generate a new master key
        master_key = secrets.token_bytes(MASTER_KEY_LENGTH)
        self._master_key_path.write_bytes(master_key)
        # Restrict permissions
        os.chmod(self._master_key_path, 0o600)
        log.info("Generated new master key at %s", self._master_key_path)
        return master_key

    # ── key storage ───────────────────────────────────────────────────

    def _key_path(self, agent_id: str) -> Path:
        """Return the path to the key file for *agent_id*."""
        safe = "".join(
            c for c in agent_id if c.isalnum() or c in "-_."
        )
        return self._keys_dir / f"{safe}.enc"

    def _save_key_entry(self, agent_id: str, keypair: KeyPair) -> None:
        """Persist a key entry to disk."""
        entry = {
            "agent_id": keypair.agent_id,
            "public_key": keypair.public_key,
            "private_key_encrypted": keypair.private_key_encrypted,
            "created_at": keypair.created_at,
            "key_id": keypair.key_id,
        }

        # Validate
        errors = validate_key_storage({agent_id: entry})
        if errors:
            raise ValueError(f"key entry validation failed: {'; '.join(errors)}")

        with self._lock:
            path = self._key_path(agent_id)
            payload = json.dumps(entry, indent=2)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.rename(path)

    def _load_key_entry(self, agent_id: str) -> dict[str, Any] | None:
        """Load a key entry from disk, or None if not found."""
        path = self._key_path(agent_id)
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            return json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load key for %s: %s", agent_id, exc)
            return None

    # ── private key encryption / decryption ────────────────────────────

    def _decrypt_private_key(
        self, encrypted_b64: str
    ) -> ed25519.Ed25519PrivateKey:
        """Decrypt a base64-encoded encrypted private key."""
        raw = base64.b64decode(encrypted_b64)
        nonce = raw[:NONCE_LENGTH]
        ciphertext = raw[NONCE_LENGTH:]

        aesgcm = AESGCM(self._master_key)
        try:
            private_bytes = aesgcm.decrypt(nonce, ciphertext, None)
        except InvalidTag:
            raise ValueError(
                "Failed to decrypt private key — master key may have changed"
            )

        return ed25519.Ed25519PrivateKey.from_private_bytes(private_bytes)

    # ── revocation list persistence ────────────────────────────────────

    def _load_revocations(self) -> list[dict[str, Any]]:
        """Load the revocation list from disk."""
        if not self._revocation_path.exists():
            return []
        try:
            raw = self._revocation_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            return data
        except (json.JSONDecodeError, OSError):
            return []

    def _save_revocations(self, data: list[dict[str, Any]]) -> None:
        """Atomically persist the revocation list."""
        errors = validate_revocation_list(data)
        if errors:
            raise ValueError(
                f"revocation list validation failed: {'; '.join(errors)}"
            )

        with self._lock:
            payload = json.dumps(data, indent=2)
            tmp = self._revocation_path.with_suffix(
                self._revocation_path.suffix + ".tmp"
            )
            tmp.write_text(payload, encoding="utf-8")
            tmp.rename(self._revocation_path)

    # ── bearer token persistence ──────────────────────────────────────

    def _load_bearer_tokens(self) -> dict[str, str]:
        """Load bearer token hashes from disk."""
        if not self._bearer_tokens_path.exists():
            return {}
        try:
            raw = self._bearer_tokens_path.read_text(encoding="utf-8")
            return json.loads(raw)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_bearer_tokens(self, data: dict[str, str]) -> None:
        """Atomically persist bearer token hashes."""
        with self._lock:
            payload = json.dumps(data, indent=2)
            tmp = self._bearer_tokens_path.with_suffix(
                self._bearer_tokens_path.suffix + ".tmp"
            )
            tmp.write_text(payload, encoding="utf-8")
            tmp.rename(self._bearer_tokens_path)

    # ── issued token persistence ──────────────────────────────────────

    def _load_issued_tokens(self) -> list[dict[str, Any]]:
        """Load issued tokens from disk."""
        if not self._issued_tokens_path.exists():
            return []
        try:
            raw = self._issued_tokens_path.read_text(encoding="utf-8")
            return json.loads(raw)
        except (json.JSONDecodeError, OSError):
            return []

    def _store_issued_token(self, token: SignedToken) -> None:
        """Append an issued token to the store."""
        issued = self._load_issued_tokens()
        # Use payload.exp for expires_at if the token itself doesn't have it
        expires_at = token.expires_at
        if expires_at is None:
            expires_at = token.payload.get("exp")
        entry = {
            "token_id": token.token_id,
            "payload": token.payload,
            "signature": token.signature,
            "signer_agent_id": token.signer_agent_id,
            "signer_public_key": token.signer_public_key,
            "issued_at": token.issued_at,
            "expires_at": expires_at,
        }
        issued.append(entry)

        with self._lock:
            payload = json.dumps(issued, indent=2)
            tmp = self._issued_tokens_path.with_suffix(
                self._issued_tokens_path.suffix + ".tmp"
            )
            tmp.write_text(payload, encoding="utf-8")
            tmp.rename(self._issued_tokens_path)
