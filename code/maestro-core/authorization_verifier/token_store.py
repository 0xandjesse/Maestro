"""Token store — persistence layer for DM tokens and revocation list.

Storage layout
--------------
* Token storage:   ``nucleus/data/dm_tokens/{token_id}.json``
* Revocation list: ``nucleus/data/revoked_tokens.json``
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from .interface import DMToken
from .schema import validate_revocation_list, validate_token_entry

log = logging.getLogger(__name__)


class TokenStore:
    """File-backed persistence for DM tokens and revocation list."""

    def __init__(
        self,
        tokens_dir: str = "nucleus/data/dm_tokens",
        revocation_path: str = "nucleus/data/revoked_tokens.json",
    ) -> None:
        self._tokens_dir = Path(tokens_dir).resolve()
        self._tokens_dir.mkdir(parents=True, exist_ok=True)

        self._revocation_path = Path(revocation_path).resolve()
        self._revocation_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()

    # ── token CRUD ─────────────────────────────────────────────────────

    def save_token(self, token: DMToken) -> None:
        """Persist a DM token to disk."""
        entry = self._token_to_dict(token)

        errors = validate_token_entry(entry)
        if errors:
            raise ValueError(f"token validation failed: {'; '.join(errors)}")

        path = self._token_path(token.token_id)
        with self._lock:
            payload = json.dumps(entry, indent=2)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.rename(path)

    def load_token(self, token_id: str) -> DMToken | None:
        """Load a DM token from disk, or None if not found."""
        path = self._token_path(token_id)
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            entry = json.loads(raw)
            return self._dict_to_token(entry)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load token %s: %s", token_id, exc)
            return None

    def delete_token(self, token_id: str) -> bool:
        """Delete a token file from disk. Returns True if it existed."""
        path = self._token_path(token_id)
        if not path.exists():
            return False
        with self._lock:
            path.unlink(missing_ok=True)
        return True

    def token_exists(self, token_id: str) -> bool:
        """Return True if a token file exists for *token_id*."""
        return self._token_path(token_id).exists()

    # ── revocation list ────────────────────────────────────────────────

    def is_revoked(self, token_id: str) -> bool:
        """Return True if *token_id* is in the revocation list."""
        revocations = self._load_revocations()
        return any(r.get("token_id") == token_id for r in revocations)

    def add_revocation(self, token_id: str, reason: str = "manual") -> None:
        """Append *token_id* to the revocation list."""
        if self.is_revoked(token_id):
            return  # idempotent — already revoked

        revocations = self._load_revocations()
        revocations.append({
            "token_id": token_id,
            "revoked_at": int(time.time() * 1000),
            "reason": reason,
        })
        self._save_revocations(revocations)

    # ── internal helpers ───────────────────────────────────────────────

    def _token_path(self, token_id: str) -> Path:
        """Return the path to the token file for *token_id*."""
        safe = "".join(c for c in token_id if c.isalnum() or c in "-_.")
        return self._tokens_dir / f"{safe}.json"

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

    # ── conversion helpers ─────────────────────────────────────────────

    @staticmethod
    def _token_to_dict(token: DMToken) -> dict[str, Any]:
        return {
            "token_id": token.token_id,
            "issuer": token.issuer,
            "subject": token.subject,
            "scope": token.scope,
            "issued_at": token.issued_at,
            "expires_at": token.expires_at,
            "signature": token.signature,
            "public_key": token.public_key,
        }

    @staticmethod
    def _dict_to_token(d: dict[str, Any]) -> DMToken:
        return DMToken(
            token_id=d.get("token_id", ""),
            issuer=d.get("issuer", ""),
            subject=d.get("subject", ""),
            scope=d.get("scope", []),
            issued_at=d.get("issued_at", 0),
            expires_at=d.get("expires_at", 0),
            signature=d.get("signature", ""),
            public_key=d.get("public_key", ""),
        )
