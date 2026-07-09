"""Policy Profiles — file-backed implementation.

Stores per-agent policy profiles on disk. Each agent's profiles live
in a single JSON file at ``~/.maestro/policy_profiles/{agent_id}.json``.

ADR-018: Policy Contexts and Normative Environments.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .interface import (
    PLAZA_PROFILE,
    PolicyProfile,
    PolicyProfileStore,
)
from .schema import validate_profile_store

# ── defaults ───────────────────────────────────────────────────────────

DEFAULT_PROFILES_DIR = "~/.maestro/policy_profiles"


class FilePolicyProfileStore(PolicyProfileStore):
    """File-backed policy profile store.

    Each agent's profiles are stored in a single JSON file.
    The plaza profile is always available as a fallback — it is
    not stored on disk because it's the universal default.
    """

    def __init__(
        self,
        profiles_dir: str = DEFAULT_PROFILES_DIR,
    ) -> None:
        self._dir = Path(os.path.expanduser(profiles_dir)).resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ── public API ─────────────────────────────────────────────────────

    def get_profile(
        self, agent_id: str, profile_name: str
    ) -> PolicyProfile | None:
        """Return the named profile for *agent_id*, or None."""
        if profile_name == "plaza":
            return PLAZA_PROFILE

        profiles = self._load(agent_id)
        for p in profiles:
            if p.name == profile_name:
                return p
        return None

    def get_active_profile(
        self, agent_id: str, token_venue: str | None = None
    ) -> PolicyProfile:
        """Return the active profile for *agent_id* given a token's venue.

        If *token_venue* is None or empty, returns the plaza profile.
        Otherwise returns the profile matching the venue name, falling
        back to plaza if no match is found.
        """
        if not token_venue:
            return PLAZA_PROFILE

        profile = self.get_profile(agent_id, token_venue)
        if profile is not None:
            return profile

        return PLAZA_PROFILE

    def set_profile(self, agent_id: str, profile: PolicyProfile) -> None:
        """Store a policy profile for *agent_id*.

        If a profile with the same name already exists, it is replaced.
        """
        if profile.name == "plaza":
            raise ValueError("Cannot override the plaza profile")

        profiles = self._load(agent_id)
        # Remove existing profile with same name
        profiles = [p for p in profiles if p.name != profile.name]
        profiles.append(profile)
        self._save(agent_id, profiles)

    def list_profiles(self, agent_id: str) -> list[PolicyProfile]:
        """Return all profiles for *agent_id*."""
        return self._load(agent_id)

    def delete_profile(self, agent_id: str, profile_name: str) -> bool:
        """Delete a named profile. Returns True if it existed."""
        if profile_name == "plaza":
            raise ValueError("Cannot delete the plaza profile")

        profiles = self._load(agent_id)
        before = len(profiles)
        profiles = [p for p in profiles if p.name != profile_name]
        if len(profiles) == before:
            return False

        self._save(agent_id, profiles)
        return True

    # ── internal helpers ───────────────────────────────────────────────

    def _agent_path(self, agent_id: str) -> Path:
        """Return the path to the profile file for *agent_id*."""
        safe = "".join(c for c in agent_id if c.isalnum() or c in "-_.")
        return self._dir / f"{safe}.json"

    def _load(self, agent_id: str) -> list[PolicyProfile]:
        """Load all profiles for *agent_id* from disk."""
        path = self._agent_path(agent_id)
        if not path.exists():
            return []

        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            return [
                PolicyProfile(
                    name=e.get("name", ""),
                    policies=e.get("policies", {}),
                    description=e.get("description", ""),
                )
                for e in data
            ]
        except (json.JSONDecodeError, OSError):
            return []

    def _save(
        self, agent_id: str, profiles: list[PolicyProfile]
    ) -> None:
        """Atomically persist profiles for *agent_id*."""
        data = [
            {
                "name": p.name,
                "policies": p.policies,
                "description": p.description,
            }
            for p in profiles
        ]

        errors = validate_profile_store(data)
        if errors:
            raise ValueError(
                f"profile validation failed: {'; '.join(errors)}"
            )

        path = self._agent_path(agent_id)
        with self._lock:
            payload = json.dumps(data, indent=2)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.rename(path)
