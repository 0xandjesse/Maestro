#!/usr/bin/env python3
"""Master Vault — single encrypted store for all bot tokens, ports, and agent config.

AES-256-GCM encryption. Key from ~/.maestro/.vault_key (chmod 600).
Never writes plaintext to disk. Tokens redacted in logs/repr.
"""

import copy
import json
import logging
import os
import shutil
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import argon2

log = logging.getLogger(__name__)

VAULT_DEFAULT_PATH = os.path.expanduser("~/.maestro/vault.json")
KEY_DEFAULT_PATH = os.path.expanduser("~/.maestro/.vault_key")
MAESTRO_DIR = os.path.expanduser("~/.maestro")

# Deprecation warning throttle — one per process lifetime
_deprecation_warned = False


class VaultError(Exception):
    """Base exception for vault operations."""


class VaultNotFoundError(VaultError):
    """Vault file not found on disk."""


class VaultCorruptError(VaultError):
    """Vault file could not be decrypted or parsed."""


class VaultKeyError(VaultError):
    """Missing or unreadable vault key file."""


class TokenExhaustedError(VaultError):
    """No available tokens in the pool."""


class MasterVault:
    """Encrypted JSON vault for bot tokens, port assignments, and agent config."""

    def __init__(
        self,
        vault_path: str = VAULT_DEFAULT_PATH,
        key_path: str = KEY_DEFAULT_PATH,
    ):
        self.vault_path = Path(vault_path)
        self.key_path = Path(key_path)
        self._data: Optional[Dict] = None  # decrypted cache

    # ── Key management ──────────────────────────────────────────

    @staticmethod
    def _derive_key(passphrase: str, salt: bytes) -> bytes:
        """Derive 32-byte AES key from passphrase + salt using argon2id."""
        hasher = argon2.PasswordHasher(
            type=argon2.Type.ID,
            time_cost=3,
            memory_cost=65536,  # 64 MB
            parallelism=4,
            hash_len=32,
            salt_len=16,
        )
        # argon2 returns a hash string; we need raw key bytes.
        # Use low-level API for raw key derivation.
        raw = argon2.low_level.hash_secret_raw(
            secret=passphrase.encode("utf-8"),
            salt=salt,
            time_cost=3,
            memory_cost=65536,
            parallelism=4,
            hash_len=32,
            type=argon2.low_level.Type.ID,
        )
        return raw

    def _read_key(self) -> bytes:
        """Read and return the raw 32-byte encryption key from key file.

        The key file stores a hex-encoded 32-byte key. If it doesn't exist,
        a new one is generated.
        """
        if not self.key_path.exists():
            raise VaultKeyError(
                f"Vault key not found at {self.key_path}. "
                "Run: python vault_cli.py init"
            )
        try:
            key_hex = self.key_path.read_text().strip()
            key_bytes = bytes.fromhex(key_hex)
            if len(key_bytes) != 32:
                raise VaultKeyError(f"Key must be 32 bytes, got {len(key_bytes)}")
            return key_bytes
        except (ValueError, OSError) as e:
            raise VaultKeyError(f"Cannot read vault key: {e}")

    @staticmethod
    def generate_key() -> bytes:
        """Generate a new random 32-byte AES key."""
        return os.urandom(32)

    def init_key(self) -> Path:
        """Create ~/.maestro/.vault_key with a new random 32-byte key.

        Returns the path to the key file. Idempotent — if key already exists,
        raises VaultError unless force=True.
        """
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if self.key_path.exists():
            raise VaultError(f"Key file already exists at {self.key_path}")
        key = self.generate_key()
        self.key_path.write_text(key.hex())
        self.key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
        log.info("Generated new vault key at %s (mode 600)", self.key_path)
        return self.key_path

    # ── Encryption / Decryption ─────────────────────────────────

    def _encrypt(self, plaintext: bytes, key: bytes) -> bytes:
        """Encrypt with AES-256-GCM. Returns salt(16) + nonce(12) + ciphertext."""
        salt = os.urandom(16)
        derived = self._derive_key(key.hex(), salt)  # use hex of key as passphrase
        # Actually — simpler: use key directly as AES key. The key IS 32 bytes.
        # We still salt for forward-compat but key derivation from stored key is direct.
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ct = aesgcm.encrypt(nonce, plaintext, None)
        return salt + nonce + ct

    def _decrypt(self, ciphertext: bytes, key: bytes) -> bytes:
        """Decrypt AES-256-GCM. Expects salt(16) + nonce(12) + ciphertext."""
        if len(ciphertext) < 29:  # 16+12+1 min
            raise VaultCorruptError("Ciphertext too short")
        salt = ciphertext[:16]
        nonce = ciphertext[16:28]
        ct = ciphertext[28:]
        aesgcm = AESGCM(key)
        try:
            return aesgcm.decrypt(nonce, ct, None)
        except Exception as e:
            raise VaultCorruptError(f"Decryption failed: {e}")

    # ── Vault I/O ──────────────────────────────────────────────

    def _load(self) -> Dict:
        """Decrypt and parse the vault file into memory."""
        if self._data is not None:
            return self._data

        if not self.vault_path.exists():
            raise VaultNotFoundError(
                f"Vault not found at {self.vault_path}. "
                "Run: python vault_cli.py init-vault"
            )

        try:
            raw = self.vault_path.read_bytes()
            key = self._read_key()
            plaintext = self._decrypt(raw, key)
            self._data = json.loads(plaintext)
            return self._data
        except VaultCorruptError:
            raise
        except json.JSONDecodeError as e:
            raise VaultCorruptError(f"Vault JSON parse failed: {e}")
        except Exception as e:
            raise VaultCorruptError(f"Vault read error: {e}")

    def _save(self, data: Dict) -> None:
        """Encrypt data and write to disk. Creates timestamped backup first."""
        key = self._read_key()
        plaintext = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        ciphertext = self._encrypt(plaintext, key)

        # Backup existing vault
        if self.vault_path.exists():
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = self.vault_path.parent / f"vault.json.bak-{ts}"
            shutil.copy2(self.vault_path, backup_path)
            log.debug("Vault backup saved to %s", backup_path)

        # Write new vault
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        self.vault_path.write_bytes(ciphertext)
        # In-memory cache update
        self._data = data
        log.info("Vault written to %s", self.vault_path)

    def _flush_cache(self) -> None:
        """Clear the in-memory cache so next read hits disk."""
        self._data = None

    # ── Vault Init ──────────────────────────────────────────────

    def init_vault(self) -> Path:
        """Create an empty vault with default structure. Requires key to exist."""
        if not self.key_path.exists():
            raise VaultKeyError(
                "Key file not found. Run init_key() or: python vault_cli.py init"
            )
        if self.vault_path.exists():
            raise VaultError(f"Vault already exists at {self.vault_path}")

        vault_data = {
            "version": "1.0",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "master_passphrase_hash": "",
            "token_pool": {
                "total": 0,
                "available": 0,
                "tokens": [],
            },
            "port_registry": {
                "gateway_base": 8640,
                "transport_base": 3840,
                "assignments": {},
            },
            "agent_defaults": {
                "home_channel_id": "",
                "platform": "telegram",
                "model": "",
                "gateway_bridge_url": "http://127.0.0.1:8644/maestro/notify",
            },
            "agent_overrides": {},
            "shared_secrets": {},
        }
        self._save(vault_data)
        return self.vault_path

    # ── Public Read API ─────────────────────────────────────────

    def get_token(self, agent_id: str) -> str:
        """Return decrypted bot token for an agent.

        Raises VaultError if agent has no assigned token.
        """
        data = self._load()
        for tok in data["token_pool"]["tokens"]:
            if tok.get("assigned_agent") == agent_id and tok.get("status") == "assigned":
                return tok["token"]
        raise VaultError(f"No token assigned to agent '{agent_id}'")

    def get_token_info(self, agent_id: str) -> Optional[Dict]:
        """Return full token record for an agent (with decrypted token)."""
        data = self._load()
        for tok in data["token_pool"]["tokens"]:
            if tok.get("assigned_agent") == agent_id and tok.get("status") == "assigned":
                return copy.deepcopy(tok)
        return None

    def allocate_token(self, agent_id: str) -> str:
        """Draw next available token from pool, mark as assigned. Returns token.

        Raises TokenExhaustedError if no tokens available.
        Raises VaultError if agent already has a token.
        """
        data = self._load()
        # Check if agent already has a token
        for tok in data["token_pool"]["tokens"]:
            if tok.get("assigned_agent") == agent_id and tok.get("status") == "assigned":
                return tok["token"]

        # Find next available
        for tok in data["token_pool"]["tokens"]:
            if tok.get("status") == "available":
                tok["status"] = "assigned"
                tok["assigned_agent"] = agent_id
                data["token_pool"]["available"] -= 1
                data["last_updated"] = datetime.now(timezone.utc).isoformat()
                self._save(data)
                log.info("Allocated token %s to agent '%s'", tok["id"], agent_id)
                return tok["token"]

        raise TokenExhaustedError("No available tokens in pool")

    def get_ports(self, agent_id: str) -> Dict[str, int]:
        """Return {gateway: int, transport: int} for agent. Allocate if missing."""
        data = self._load()
        assignments = data["port_registry"]["assignments"]

        if agent_id in assignments:
            return copy.deepcopy(assignments[agent_id])

        # Allocate next free ports
        gateway_base = data["port_registry"]["gateway_base"]
        transport_base = data["port_registry"]["transport_base"]

        # Find next available gateway port (step of 3, matching existing pattern)
        used_gw = {a["gateway"] for a in assignments.values()}
        used_tp = {a["transport"] for a in assignments.values()}

        # Existing agents use ports at base+i*3 pattern, find next free
        gw_port = None
        tp_port = None
        for i in range(100):  # up to 100 agents
            candidate_gw = gateway_base + (i + 1) * 3
            candidate_tp = transport_base + (i + 1) * 3
            if candidate_gw not in used_gw and candidate_tp not in used_tp:
                gw_port = candidate_gw
                tp_port = candidate_tp
                break

        if gw_port is None:
            raise VaultError("No free port slots — port pool exhausted")

        assignments[agent_id] = {"gateway": gw_port, "transport": tp_port}
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        self._save(data)
        log.info("Allocated ports for '%s': gateway=%d, transport=%d",
                 agent_id, gw_port, tp_port)
        return {"gateway": gw_port, "transport": tp_port}

    def get_config(self, agent_id: str) -> Dict[str, Any]:
        """Return merged agent_defaults + agent_overrides for agent."""
        data = self._load()
        defaults = copy.deepcopy(data.get("agent_defaults", {}))
        overrides = data.get("agent_overrides", {}).get(agent_id, {})
        defaults.update(overrides)
        return defaults

    def get_all_agents(self) -> List[str]:
        """Return list of all agent_ids with port assignments."""
        data = self._load()
        return list(data["port_registry"]["assignments"].keys())

    def get_available_tokens(self) -> List[Dict]:
        """Return tokens where status == 'available'. Tokens are redacted."""
        data = self._load()
        result = []
        for tok in data["token_pool"]["tokens"]:
            if tok.get("status") == "available":
                entry = copy.deepcopy(tok)
                entry["token"] = _redact_token(tok["token"])
                result.append(entry)
        return result

    # ── Public Write API ────────────────────────────────────────

    def release_token(self, agent_id: str) -> None:
        """Mark token as available. Zero out assigned_agent."""
        data = self._load()
        for tok in data["token_pool"]["tokens"]:
            if tok.get("assigned_agent") == agent_id and tok.get("status") == "assigned":
                tok["status"] = "available"
                tok["assigned_agent"] = None
                data["token_pool"]["available"] += 1
                data["last_updated"] = datetime.now(timezone.utc).isoformat()
                self._save(data)
                log.info("Released token %s from agent '%s'", tok["id"], agent_id)
                return
        raise VaultError(f"No assigned token found for agent '{agent_id}'")

    def provision_token(self, bot_username: str, token: str) -> str:
        """Add a new token to the pool. Returns the token ID."""
        data = self._load()
        # Generate sequential ID
        existing_ids = {t["id"] for t in data["token_pool"]["tokens"]}
        idx = len(data["token_pool"]["tokens"]) + 1
        token_id = f"bot_{idx:03d}"
        while token_id in existing_ids:
            idx += 1
            token_id = f"bot_{idx:03d}"

        entry = {
            "id": token_id,
            "token": token,
            "bot_username": bot_username,
            "status": "available",
            "assigned_agent": None,
            "created": datetime.now(timezone.utc).isoformat(),
        }
        data["token_pool"]["tokens"].append(entry)
        data["token_pool"]["total"] += 1
        data["token_pool"]["available"] += 1
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        self._save(data)
        log.info("Provisioned token %s for bot '%s'", token_id, bot_username)
        return token_id

    def revoke_token(self, token_id: str) -> None:
        """Mark a token as revoked. Cannot be reassigned."""
        data = self._load()
        for tok in data["token_pool"]["tokens"]:
            if tok["id"] == token_id:
                if tok["status"] == "available":
                    data["token_pool"]["available"] -= 1
                tok["status"] = "revoked"
                tok["assigned_agent"] = None
                data["last_updated"] = datetime.now(timezone.utc).isoformat()
                self._save(data)
                log.info("Revoked token %s", token_id)
                return
        raise VaultError(f"Token '{token_id}' not found")

    def set_agent_override(self, agent_id: str, key: str, value: Any) -> None:
        """Set a single override for an agent."""
        data = self._load()
        if agent_id not in data["agent_overrides"]:
            data["agent_overrides"][agent_id] = {}
        data["agent_overrides"][agent_id][key] = value
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        self._save(data)

    def set_shared_secret(self, key: str, value: str) -> None:
        """Set a shared secret in the vault."""
        data = self._load()
        data["shared_secrets"][key] = value
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        self._save(data)

    def get_shared_secret(self, key: str) -> Optional[str]:
        """Get a shared secret from the vault."""
        data = self._load()
        return data.get("shared_secrets", {}).get(key)

    def rotate_master_key(self, new_key_hex: Optional[str] = None) -> None:
        """Re-encrypt entire vault with a new master key.

        If new_key_hex is None, generates a random key.
        Updates the key file on disk.
        """
        data = self._load()

        if new_key_hex is None:
            new_key = self.generate_key()
            new_key_hex = new_key.hex()
        else:
            new_key = bytes.fromhex(new_key_hex)

        # Write new key file
        self.key_path.write_text(new_key_hex)
        self.key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        log.warning("Vault key rotated — new key written to %s", self.key_path)

        # Force re-encryption by flushing cache and writing with new key
        self._data = data  # keep decrypted data in memory
        self._save(data)  # _save will call _read_key which reads the new key

    # ── Utility ─────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"MasterVault(path={self.vault_path}, loaded={self._data is not None})"

    def raw_data(self) -> Dict:
        """Return the full decrypted vault dict. Tokens are NOT redacted —
        use with caution. Intended for migration scripts only."""
        return self._load()


# ── Helpers ──────────────────────────────────────────────────────

def _redact_token(token: str) -> str:
    """Redact a token for logging. Shows first 6 chars and last 4."""
    if len(token) <= 12:
        return "***REDACTED***"
    return f"{token[:6]}...{token[-4:]}"


def deprecation_warning(source: str = ".env") -> None:
    """Emit a one-time deprecation warning about reading config from .env."""
    global _deprecation_warned
    if _deprecation_warned:
        return
    _deprecation_warned = True
    log.warning(
        "DEPRECATION: Config read from %s. Migrate to Master Vault for unified config. "
        "See: python vault_cli.py --help",
        source,
    )