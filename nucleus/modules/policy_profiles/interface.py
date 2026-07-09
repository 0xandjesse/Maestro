"""Policy Profiles — Interface Contract.

Defines PolicyProfile, IdentityInvariant, and the PolicyProfileStore
abstract base class.

ADR-018: Policy Contexts and Normative Environments.

Identity Invariants are the agent's constitution — things it never does,
constant across all contexts. Policy Profiles are named sets of policies
that an agent activates when operating in a specific environment. Only
one profile is active per interaction. The token selects the profile.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


# ── Identity Invariants ─────────────────────────────────────────────────

class IdentityInvariant(Enum):
    """Things an agent never does, regardless of context.

    These are not policies — they are the agent's constitution.
    No Venue can require an agent to violate them. If a Venue's
    participation contract demands something that conflicts with
    an identity invariant, the agent cannot enter that Venue.
    The invariant wins.
    """

    NEVER_REVEAL_PRIVATE_KEYS = "never_reveal_private_keys"
    NEVER_FORGE_PROVENANCE = "never_forge_provenance"
    NEVER_VIOLATE_MEMORY_INTEGRITY = "never_violate_memory_integrity"
    NEVER_IMPERSONATE_ANOTHER_AGENT = "never_impersonate_another_agent"


# The set of invariants every agent must uphold.
IDENTITY_INVARIANTS = frozenset(IdentityInvariant)


# ── Policy Profile ─────────────────────────────────────────────────────

@dataclass
class PolicyProfile:
    """A named set of policies for a specific normative environment.

    Attributes
    ----------
    name : str
        Profile name, e.g. "plaza", "taskmaster", "boxing-gym".
    policies : dict[str, object]
        Policy key-value pairs. Keys are policy names (e.g.
        "require_signatures", "accept_tokens"). Values are the
        policy settings (bool, list, str, etc.).
    description : str
        Human-readable description of when this profile is used.
    """

    name: str
    policies: dict[str, object] = field(default_factory=dict)
    description: str = ""

    def get(self, key: str, default: object = None) -> object:
        """Get a policy value by key, with a default."""
        return self.policies.get(key, default)

    def requires_signatures(self) -> bool:
        """Return True if this profile requires signatures."""
        return bool(self.policies.get("require_signatures", True))

    def accepts_token_from(self, issuer: str) -> bool:
        """Return True if this profile accepts tokens from *issuer*."""
        accepted = self.policies.get("accept_tokens", ["self-issued"])
        if isinstance(accepted, list):
            return issuer in accepted or "self-issued" in accepted
        return False


# ── Default Plaza Profile ──────────────────────────────────────────────

PLAZA_PROFILE = PolicyProfile(
    name="plaza",
    policies={
        "require_signatures": True,
        "accept_tokens": ["self-issued"],
        "provenance_required": False,
    },
    description="Default context — no central authority, each agent sovereign.",
)


# ── Policy Profile Store ───────────────────────────────────────────────

class PolicyProfileStore(ABC):
    """Abstract interface for per-agent policy profile storage.

    Each agent maintains one or more policy profiles. Only one profile
    is active for a given interaction. The token selects the profile.
    """

    @abstractmethod
    def get_profile(self, agent_id: str, profile_name: str) -> PolicyProfile | None:
        """Return the named profile for *agent_id*, or None."""
        ...

    @abstractmethod
    def get_active_profile(
        self, agent_id: str, token_venue: str | None = None
    ) -> PolicyProfile:
        """Return the active profile for *agent_id* given a token's venue.

        If *token_venue* is None or empty, returns the default (plaza) profile.
        Otherwise returns the profile matching the venue name, falling back
        to plaza if no match is found.
        """
        ...

    @abstractmethod
    def set_profile(self, agent_id: str, profile: PolicyProfile) -> None:
        """Store a policy profile for *agent_id*."""
        ...

    @abstractmethod
    def list_profiles(self, agent_id: str) -> list[PolicyProfile]:
        """Return all profiles for *agent_id*."""
        ...

    @abstractmethod
    def delete_profile(self, agent_id: str, profile_name: str) -> bool:
        """Delete a named profile. Returns True if it existed."""
        ...
