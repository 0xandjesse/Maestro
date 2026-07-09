"""Tests for the Policy Profiles module.

Covers:
* Plaza profile is always available
* Profile CRUD (set, get, list, delete)
* Active profile selection by token venue
* Identity invariants are immutable
* Schema validation
* Persistence across reloads
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from nucleus.modules.policy_profiles import (
    IDENTITY_INVARIANTS,
    PLAZA_PROFILE,
    FilePolicyProfileStore,
    IdentityInvariant,
    PolicyProfile,
    validate_profile_store,
)


# ── fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def tmp_dir():
    """Create a temporary directory for isolated profile storage."""
    with tempfile.TemporaryDirectory(prefix="test_profiles_") as td:
        yield td


@pytest.fixture
def store(tmp_dir):
    """Return a FilePolicyProfileStore pointed at a temp directory."""
    return FilePolicyProfileStore(profiles_dir=tmp_dir)


# ── identity invariants ────────────────────────────────────────────────

class TestIdentityInvariants:
    def test_all_invariants_defined(self):
        """All four identity invariants exist."""
        assert len(IDENTITY_INVARIANTS) == 4
        assert IdentityInvariant.NEVER_REVEAL_PRIVATE_KEYS in IDENTITY_INVARIANTS
        assert IdentityInvariant.NEVER_FORGE_PROVENANCE in IDENTITY_INVARIANTS
        assert IdentityInvariant.NEVER_VIOLATE_MEMORY_INTEGRITY in IDENTITY_INVARIANTS
        assert IdentityInvariant.NEVER_IMPERSONATE_ANOTHER_AGENT in IDENTITY_INVARIANTS

    def test_invariants_are_immutable(self):
        """IDENTITY_INVARIANTS is a frozenset — cannot be modified."""
        with pytest.raises(AttributeError):
            IDENTITY_INVARIANTS.add("something_new")  # type: ignore


# ── plaza profile ──────────────────────────────────────────────────────

class TestPlazaProfile:
    def test_plaza_is_default(self, store):
        """Plaza profile is returned when no venue is specified."""
        profile = store.get_active_profile("any-agent", token_venue=None)
        assert profile.name == "plaza"
        assert profile.requires_signatures() is True

    def test_plaza_is_fallback(self, store):
        """Plaza profile is returned when venue doesn't match any profile."""
        profile = store.get_active_profile("any-agent", token_venue="nonexistent")
        assert profile.name == "plaza"

    def test_plaza_cannot_be_overridden(self, store):
        """Setting a profile named 'plaza' raises ValueError."""
        with pytest.raises(ValueError, match="plaza"):
            store.set_profile("agent-1", PolicyProfile(name="plaza"))

    def test_plaza_cannot_be_deleted(self, store):
        """Deleting the plaza profile raises ValueError."""
        with pytest.raises(ValueError, match="plaza"):
            store.delete_profile("agent-1", "plaza")

    def test_plaza_get_returns_constant(self, store):
        """get_profile('plaza') returns the constant, not from disk."""
        profile = store.get_profile("any-agent", "plaza")
        assert profile is PLAZA_PROFILE


# ── profile CRUD ───────────────────────────────────────────────────────

class TestProfileCRUD:
    def test_set_and_get_profile(self, store):
        profile = PolicyProfile(
            name="taskmaster",
            policies={"require_signatures": True, "accept_tokens": ["self-issued", "taskmaster-issued"]},
            description="TaskMaster venue profile",
        )
        store.set_profile("agent-1", profile)

        retrieved = store.get_profile("agent-1", "taskmaster")
        assert retrieved is not None
        assert retrieved.name == "taskmaster"
        assert retrieved.requires_signatures() is True
        assert retrieved.policies["accept_tokens"] == ["self-issued", "taskmaster-issued"]

    def test_set_overwrites_existing(self, store):
        store.set_profile("agent-1", PolicyProfile(name="taskmaster", policies={"require_signatures": True}))
        store.set_profile("agent-1", PolicyProfile(name="taskmaster", policies={"require_signatures": False}))

        retrieved = store.get_profile("agent-1", "taskmaster")
        assert retrieved.requires_signatures() is False

    def test_list_profiles(self, store):
        store.set_profile("agent-1", PolicyProfile(name="taskmaster"))
        store.set_profile("agent-1", PolicyProfile(name="boxing-gym"))

        profiles = store.list_profiles("agent-1")
        assert len(profiles) == 2
        names = {p.name for p in profiles}
        assert names == {"taskmaster", "boxing-gym"}

    def test_list_profiles_empty(self, store):
        profiles = store.list_profiles("no-profiles-agent")
        assert profiles == []

    def test_delete_profile(self, store):
        store.set_profile("agent-1", PolicyProfile(name="taskmaster"))
        assert store.delete_profile("agent-1", "taskmaster") is True
        assert store.get_profile("agent-1", "taskmaster") is None

    def test_delete_nonexistent(self, store):
        assert store.delete_profile("agent-1", "nonexistent") is False

    def test_get_nonexistent(self, store):
        assert store.get_profile("agent-1", "nonexistent") is None


# ── active profile selection ───────────────────────────────────────────

class TestActiveProfile:
    def test_token_venue_selects_profile(self, store):
        store.set_profile("agent-1", PolicyProfile(
            name="taskmaster",
            policies={"require_signatures": True, "accept_tokens": ["taskmaster-issued"]},
        ))

        profile = store.get_active_profile("agent-1", token_venue="taskmaster")
        assert profile.name == "taskmaster"

    def test_unknown_venue_falls_back_to_plaza(self, store):
        profile = store.get_active_profile("agent-1", token_venue="unknown-venue")
        assert profile.name == "plaza"

    def test_none_venue_returns_plaza(self, store):
        profile = store.get_active_profile("agent-1", token_venue=None)
        assert profile.name == "plaza"

    def test_empty_venue_returns_plaza(self, store):
        profile = store.get_active_profile("agent-1", token_venue="")
        assert profile.name == "plaza"

    def test_multiple_agents_independent(self, store):
        store.set_profile("alice", PolicyProfile(name="taskmaster"))
        store.set_profile("bob", PolicyProfile(name="boxing-gym"))

        assert store.get_active_profile("alice", "taskmaster").name == "taskmaster"
        assert store.get_active_profile("bob", "boxing-gym").name == "boxing-gym"
        # alice doesn't have boxing-gym
        assert store.get_active_profile("alice", "boxing-gym").name == "plaza"


# ── policy helpers ─────────────────────────────────────────────────────

class TestPolicyHelpers:
    def test_requires_signatures_default(self):
        profile = PolicyProfile(name="test")
        assert profile.requires_signatures() is True

    def test_requires_signatures_false(self):
        profile = PolicyProfile(name="test", policies={"require_signatures": False})
        assert profile.requires_signatures() is False

    def test_accepts_self_issued(self):
        profile = PolicyProfile(name="test", policies={"accept_tokens": ["self-issued"]})
        assert profile.accepts_token_from("self-issued") is True
        assert profile.accepts_token_from("any-agent") is True  # self-issued accepts all

    def test_accepts_specific_issuer(self):
        profile = PolicyProfile(name="test", policies={"accept_tokens": ["taskmaster-issued"]})
        assert profile.accepts_token_from("taskmaster-issued") is True
        assert profile.accepts_token_from("other") is False

    def test_get_with_default(self):
        profile = PolicyProfile(name="test", policies={"foo": "bar"})
        assert profile.get("foo") == "bar"
        assert profile.get("missing", "default") == "default"
        assert profile.get("missing") is None


# ── schema validation ──────────────────────────────────────────────────

class TestSchemaValidation:
    def test_valid_store(self):
        errors = validate_profile_store([
            {"name": "taskmaster", "policies": {"require_signatures": True}},
            {"name": "boxing-gym", "policies": {"relay_authenticated": True}},
        ])
        assert errors == []

    def test_not_a_list(self):
        errors = validate_profile_store({"not": "a list"})
        assert any("array" in e for e in errors)

    def test_entry_not_a_dict(self):
        errors = validate_profile_store(["not a dict"])
        assert any("not a dict" in e for e in errors)

    def test_missing_name(self):
        errors = validate_profile_store([
            {"policies": {"require_signatures": True}},
        ])
        assert any("name" in e for e in errors)

    def test_empty_name(self):
        errors = validate_profile_store([
            {"name": "", "policies": {}},
        ])
        assert any("name" in e for e in errors)

    def test_missing_policies(self):
        errors = validate_profile_store([
            {"name": "test"},
        ])
        assert any("policies" in e for e in errors)

    def test_duplicate_names(self):
        errors = validate_profile_store([
            {"name": "dup", "policies": {}},
            {"name": "dup", "policies": {}},
        ])
        assert any("duplicate" in e for e in errors)

    def test_unknown_policy_key(self):
        errors = validate_profile_store([
            {"name": "test", "policies": {"bogus_key": True}},
        ])
        assert any("unknown policy key" in e for e in errors)

    def test_bad_description_type(self):
        errors = validate_profile_store([
            {"name": "test", "policies": {}, "description": 123},
        ])
        assert any("description" in e for e in errors)


# ── persistence ────────────────────────────────────────────────────────

class TestPersistence:
    def test_data_survives_reload(self, tmp_dir):
        store1 = FilePolicyProfileStore(profiles_dir=tmp_dir)
        store1.set_profile("agent-1", PolicyProfile(
            name="taskmaster",
            policies={"require_signatures": True},
        ))

        store2 = FilePolicyProfileStore(profiles_dir=tmp_dir)
        profile = store2.get_profile("agent-1", "taskmaster")
        assert profile is not None
        assert profile.name == "taskmaster"
        assert profile.requires_signatures() is True

    def test_file_is_valid_json(self, tmp_dir):
        store = FilePolicyProfileStore(profiles_dir=tmp_dir)
        store.set_profile("agent-1", PolicyProfile(name="taskmaster"))
        store.set_profile("agent-1", PolicyProfile(name="boxing-gym"))

        path = Path(tmp_dir) / "agent-1.json"
        raw = path.read_text()
        data = json.loads(raw)
        assert isinstance(data, list)
        assert len(data) == 2

    def test_atomic_write_no_partial(self, tmp_dir):
        store = FilePolicyProfileStore(profiles_dir=tmp_dir)
        store.set_profile("agent-1", PolicyProfile(name="taskmaster"))

        path = Path(tmp_dir) / "agent-1.json"
        before = path.read_text()

        with pytest.raises(ValueError):
            store._save("agent-1", [
                PolicyProfile(name="", policies={}),  # invalid
            ])

        after = path.read_text()
        assert after == before

    def test_no_temp_file_left_behind(self, tmp_dir):
        store = FilePolicyProfileStore(profiles_dir=tmp_dir)
        store.set_profile("agent-1", PolicyProfile(name="taskmaster"))

        tmp_path = Path(tmp_dir) / "agent-1.json.tmp"
        assert not tmp_path.exists()
