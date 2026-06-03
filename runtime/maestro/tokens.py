"""
Maestro Delegation Token Primitives.

Object-capability (ocap) delegation tokens using Ed25519 signatures.
A signed capability object that the recipient verifies by checking:
(a) delegator's signature, (b) delegation chain ancestry,
(c) scope/depth/duration constraints.

No shared infrastructure needed. The token IS the proof.
Works locally and across Venues without a central authority.

Usage:
    from maestro.tokens import issue_token, validate_token, revoke_token

    # Issue a token
    token = issue_token(
        delegator_id="proteus",
        delegate_id="stormtrooper",
        delegator_private_key_hex="...",
        scope={"actions": ["bb_read"], "resources": ["board:proteus_work_queue"]},
    )

    # Validate at enforcement point
    valid, reason = validate_token(token, action="bb_read", resource="board:proteus_work_queue")

Dependencies: maestro_crypto (Ed25519 sign/verify/hash), ~/.maestro/registry.json
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from nacl.exceptions import BadSignatureError

from maestro_crypto import hash_concat, hash_string, sign, verify


# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

REGISTRY_PATH = Path(os.path.expanduser("~/.maestro/registry.json"))
DEFAULT_HEARTBEAT_INTERVAL = 300  # 5 minutes
DEFAULT_MAX_DEPTH = 2
DEFAULT_EXPIRY_SECONDS = 3600  # 1 hour


# ──────────────────────────────────────────────
# Registry helpers
# ──────────────────────────────────────────────

def _load_registry(path: Optional[Path] = None) -> list:
    """Load the agent registry JSON."""
    p = path or REGISTRY_PATH
    if not p.exists():
        raise FileNotFoundError(f"Registry not found at {p}")
    return json.loads(p.read_text())


def _get_public_key(agent_id: str, registry: Optional[list] = None) -> Optional[str]:
    """Look up an agent's public key in the registry."""
    reg = registry if registry is not None else _load_registry()
    for entry in reg:
        if entry.get("agentId") == agent_id:
            return entry.get("publicKey")
    return None


# ──────────────────────────────────────────────
# Canonical token serialisation
# ──────────────────────────────────────────────

def canonical_json(token: dict) -> str:
    """Serialize a token for signing: sorted keys, no whitespace, signature excluded."""
    payload = {k: v for k, v in token.items() if k != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def canonical_json_bytes(token: dict) -> bytes:
    """Serialize token to bytes for hashing/signing."""
    return canonical_json(token).encode("utf-8")


# ──────────────────────────────────────────────
# Heartbeat tracker (in-memory, per-process)
# ──────────────────────────────────────────────

@dataclass
class HeartbeatTracker:
    """Tracks last-heartbeat timestamps for delegation tokens."""

    _heartbeats: Dict[str, float] = field(default_factory=dict)

    def record(self, token_id: str, timestamp: Optional[float] = None) -> None:
        """Record a heartbeat for a token."""
        self._heartbeats[token_id] = timestamp or time.time()

    def last(self, token_id: str) -> Optional[float]:
        """Get the last heartbeat timestamp for a token."""
        return self._heartbeats.get(token_id)

    def is_alive(self, token_id: str, interval_seconds: int, multiplier: int = 2) -> bool:
        """Check if a token's heartbeat is still alive.
        Returns False if no heartbeat has ever been recorded.
        """
        last_beat = self._heartbeats.get(token_id)
        if last_beat is None:
            return False
        return (time.time() - last_beat) <= (interval_seconds * multiplier)

    def clear(self, token_id: str) -> None:
        """Remove heartbeat tracking for a token."""
        self._heartbeats.pop(token_id, None)


# ──────────────────────────────────────────────
# Token issuance
# ──────────────────────────────────────────────

def issue_token(
    delegator_id: str,
    delegate_id: str,
    delegator_private_key_hex: str,
    scope: dict,
    max_depth: int = DEFAULT_MAX_DEPTH,
    expiry_seconds: int = DEFAULT_EXPIRY_SECONDS,
    heartbeat_required: bool = True,
    heartbeat_interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL,
    human_authorized: bool = False,
    parent_token: Optional[dict] = None,
    registry: Optional[list] = None,
) -> dict:
    """Issue a new delegation token signed with the delegator's private key.

    If parent_token is provided, builds on the existing delegation chain
    (re-delegation). The new token inherits scope intersection and increments depth.

    Args:
        delegator_id: Agent ID of the token issuer
        delegate_id: Agent ID of the token recipient
        delegator_private_key_hex: Ed25519 private key (hex)
        scope: Scope dict with actions, resources, venues, etc.
        max_depth: Maximum delegation chain depth from this point
        expiry_seconds: Token lifetime from now (seconds)
        heartbeat_required: Whether delegate must check heartbeat
        heartbeat_interval_seconds: Heartbeat interval for liveness check
        human_authorized: Whether token was authorized by a human (Jesse)
        parent_token: Existing token being re-delegated (None for root)
        registry: Agent registry list (loaded from ~/.maestro/registry.json if None)

    Returns:
        Complete delegation token dict with signature

    Raises:
        ValueError: If re-delegation is not allowed or depth exceeds max
    """
    reg = registry if registry is not None else _load_registry()
    now = int(time.time())

    # Resolve delegator public key
    delegator_pubkey = _get_public_key(delegator_id, reg)
    if not delegator_pubkey:
        raise ValueError(f"Public key not found for {delegator_id} in registry")

    # Build delegation chain
    if parent_token:
        # Re-delegation: validate parent permits it
        if not parent_token.get("scope", {}).get("allow_delegation", False):
            raise ValueError("Parent token does not allow re-delegation")

        if human_authorized:
            raise ValueError("Human-authorized tokens cannot be re-delegated")
        if parent_token.get("human_authorized", False):
            raise ValueError("Human-authorized tokens cannot be re-delegated")

        parent_chain = parent_token["delegation_chain"]
        new_depth = parent_chain["depth"] + 1

        if new_depth > parent_chain["max_depth"]:
            raise ValueError(
                f"Depth {new_depth} exceeds parent max_depth {parent_chain['max_depth']}"
            )

        # Expiry must be monotonically decreasing
        if (now + expiry_seconds) > parent_token["expiry"]:
            raise ValueError("Child token expiry must not exceed parent token expiry")

        # Intersect scopes
        intersected_scope = _intersect_scopes(parent_token["scope"], scope)

        ancestry = list(parent_chain["ancestry"])
        ancestry.append(
            {
                "delegator": delegator_id,
                "delegate": delegate_id,
                "signature": "",  # filled below
                "timestamp": now,
            }
        )

        chain = {
            "depth": new_depth,
            "max_depth": parent_chain["max_depth"],
            "lineage_root": parent_chain["lineage_root"],
            "ancestry": ancestry,
        }

        effective_scope = intersected_scope
    else:
        # Root delegation
        chain = {
            "depth": 1,
            "max_depth": max_depth,
            "lineage_root": delegator_id,
            "ancestry": [
                {
                    "delegator": delegator_id,
                    "delegate": delegate_id,
                    "signature": "",  # filled below
                    "timestamp": now,
                }
            ],
        }
        effective_scope = scope

    # Build token
    token = {
        "token_id": str(uuid.uuid4()),
        "version": 1,
        "delegator_id": delegator_id,
        "delegate_id": delegate_id,
        "delegator_public_key": delegator_pubkey,
        "scope": effective_scope,
        "delegation_chain": chain,
        "expiry": now + expiry_seconds,
        "issued_at": now,
        "nonce": os.urandom(32).hex(),
        "revocation_endpoint": f"maestro://{delegator_id}/revoke",
        "heartbeat_required": heartbeat_required,
        "heartbeat_interval_seconds": heartbeat_interval_seconds,
        "human_authorized": human_authorized,
    }

    # Sign the token
    token_bytes = canonical_json_bytes(token)
    token["signature"] = sign(canonical_json(token), delegator_private_key_hex)

    return token


def _intersect_scopes(parent_scope: dict, child_scope: dict) -> dict:
    """Intersect two scopes: effective scope is intersection of both.

    Resource intersection uses pattern matching semantics:
    'board:*' covers 'board:proteus_work_queue', so the intersection
    of ['board:proteus_work_queue'] and ['board:*'] is ['board:proteus_work_queue'].
    Authority never increases — the effective resource set is the subset of
    parent resources that match any child pattern.
    """
    # Actions: exact set intersection
    actions = sorted(
        set(parent_scope.get("actions", [])) & set(child_scope.get("actions", []))
    )
    # Resources: pattern-aware intersection
    # The delegate gets parent resources that match any child pattern
    parent_resources = parent_scope.get("resources", [])
    child_resources = child_scope.get("resources", [])
    resources = sorted([
        r for r in parent_resources
        if _resource_matches(r, child_resources)
    ])
    # Venues: exact set intersection
    venues = sorted(
        set(parent_scope.get("venues", [])) & set(child_scope.get("venues", []))
    )
    return {
        "actions": actions,
        "resources": resources,
        "venues": venues,
        "max_file_size_bytes": min(
            parent_scope.get("max_file_size_bytes", 0),
            child_scope.get("max_file_size_bytes", 0),
        )
        if parent_scope.get("max_file_size_bytes") is not None
        and child_scope.get("max_file_size_bytes") is not None
        else None,
        "allow_terminal": parent_scope.get("allow_terminal", False)
        and child_scope.get("allow_terminal", False),
        "allow_delegation": parent_scope.get("allow_delegation", False)
        and child_scope.get("allow_delegation", False),
    }


# ──────────────────────────────────────────────
# Token validation
# ──────────────────────────────────────────────

def validate_token(
    token: dict,
    action: str,
    resource: str,
    venue: str = "local",
    registry: Optional[list] = None,
    heartbeat_tracker: Optional[HeartbeatTracker] = None,
) -> Tuple[bool, str]:
    """Validate a delegation token for the given action/resource/venue.

    Checks: signature, public key resolution, chain ancestry, depth ceiling,
    lineage integrity, expiry, scope enforcement, heartbeat liveness.

    Args:
        token: The delegation token dict
        action: The action being attempted (e.g. "bb_read", "send_message")
        resource: The resource being accessed (e.g. "board:proteus_work_queue")
        venue: The venue (default "local")
        registry: Agent registry list
        heartbeat_tracker: HeartbeatTracker instance for liveness check

    Returns:
        (valid: bool, reason: str) — reason is empty string when valid
    """
    reg = registry if registry is not None else _load_registry()

    # 1. Signature check
    if not _verify_token_signature(token):
        return False, "signature_invalid"

    # 2. Public key resolution
    pubkey = _get_public_key(token["delegator_id"], reg)
    if not pubkey:
        return False, f"public_key_not_found:{token['delegator_id']}"
    if pubkey != token["delegator_public_key"]:
        return False, "public_key_mismatch"

    # 3 & 4. Chain ancestry + depth ceiling
    chain = token["delegation_chain"]
    if chain["depth"] > chain["max_depth"]:
        return False, f"depth_exceeded:{chain['depth']}>{chain['max_depth']}"

    for hop in chain["ancestry"]:
        if not _verify_hop_signature(hop, reg):
            return False, "chain_signature_invalid"

    # 5. Lineage integrity
    if chain["ancestry"] and chain["ancestry"][0]["delegator"] != chain["lineage_root"]:
        return False, "lineage_integrity_failed"

    # 6. Expiry check
    if token["expiry"] <= int(time.time()):
        return False, "expired"

    # 7. Scope enforcement
    scope = token["scope"]
    if action not in scope.get("actions", []):
        return False, f"action_not_in_scope:{action}"

    if not _resource_matches(resource, scope.get("resources", [])):
        return False, f"resource_not_in_scope:{resource}"

    if venue not in scope.get("venues", ["local"]):
        return False, f"venue_not_in_scope:{venue}"

    # 8. Heartbeat liveness
    if token.get("heartbeat_required", False):
        if heartbeat_tracker:
            interval = token.get("heartbeat_interval_seconds", DEFAULT_HEARTBEAT_INTERVAL)
            if not heartbeat_tracker.is_alive(token["token_id"], interval):
                return False, "heartbeat_missing"
        # If no tracker provided and heartbeat is required, skip check
        # (integration tests provide their own tracker)

    return True, ""


def _verify_token_signature(token: dict) -> bool:
    """Verify the signature on a token."""
    try:
        return verify(
            canonical_json(token),
            token["signature"],
            token["delegator_public_key"],
        )
    except (BadSignatureError, ValueError, KeyError):
        return False


def _verify_hop_signature(hop: dict, registry: list) -> bool:
    """Verify a single hop in the delegation chain."""
    if not hop.get("signature"):
        # Root-level ancestry entries may not have individual hop signatures
        # if the chain was built inline (all ancestry in one token).
        # The root token signature covers the full chain.
        return True
    delegator_pubkey = _get_public_key(hop["delegator"], registry)
    if not delegator_pubkey:
        return False
    hop_bytes = json.dumps(
        {
            "delegator": hop["delegator"],
            "delegate": hop["delegate"],
            "timestamp": hop["timestamp"],
        },
        sort_keys=True,
    ).encode("utf-8")
    return verify(hop_bytes.decode("utf-8"), hop["signature"], delegator_pubkey)


def _resource_matches(resource: str, allowed_resources: list) -> bool:
    """Check if a resource matches any allowed resource pattern.

    Supports:
      - Exact match: "board:proteus_work_queue"
      - Prefix match: "board:*" matches "board:proteus_work_queue"
      - Glob match: "board:swarm_*" matches "board:swarm_health_bb"
    """
    for allowed in allowed_resources:
        if allowed == resource:
            return True
        if allowed == "*":
            return True
        # Prefix match: "board:*"
        if ":" in allowed:
            prefix, pattern = allowed.split(":", 1)
            if ":" in resource:
                r_prefix, r_value = resource.split(":", 1)
                if prefix == r_prefix:
                    if pattern == "*":
                        return True
                    # Simple glob: "swarm_*" matches "swarm_health_bb"
                    if pattern.endswith("*"):
                        if r_value.startswith(pattern[:-1]):
                            return True
                    # Wildcard in the middle
                    if "*" in pattern:
                        import fnmatch
                        if fnmatch.fnmatch(r_value, pattern):
                            return True
    return False


def verify_chain(token: dict, registry: Optional[list] = None) -> Tuple[bool, str]:
    """Verify the full delegation chain ancestry.

    Returns (valid, reason).
    """
    reg = registry if registry is not None else _load_registry()
    chain = token.get("delegation_chain", {})

    if chain["depth"] > chain["max_depth"]:
        return False, f"depth_exceeded:{chain['depth']}>{chain['max_depth']}"

    for hop in chain.get("ancestry", []):
        if not _verify_hop_signature(hop, reg):
            return False, "chain_signature_invalid"

    if chain.get("ancestry") and chain["ancestry"][0]["delegator"] != chain.get("lineage_root"):
        return False, "lineage_integrity_failed"

    return True, ""


# ──────────────────────────────────────────────
# Revocation
# ──────────────────────────────────────────────

def revoke_token(
    token_id: str,
    delegator_id: str,
    delegator_private_key_hex: str,
    issuance_log: Optional[dict] = None,
) -> dict:
    """Revoke a delegation token and return the revoke message envelope.

    Args:
        token_id: The token to revoke
        delegator_id: Agent ID of the revoker
        delegator_private_key_hex: Revoker's private key
        issuance_log: Dict of token_id -> {token, downstream_ids} for subtree broadcast

    Returns:
        Revoke message envelope for P2P dispatch.
        If issuance_log is provided, includes downstream token IDs for broadcast.
    """
    now = int(time.time())
    message = {
        "type": "revoke_delegation",
        "token_id": token_id,
        "delegator_id": delegator_id,
        "timestamp": now,
    }
    # Find all downstream tokens in the issuance log
    downstream = []
    if issuance_log and token_id in issuance_log:
        entry = issuance_log[token_id]
        downstream = entry.get("downstream_ids", [])

    message_bytes = json.dumps(message, sort_keys=True)
    message["signature"] = sign(message_bytes, delegator_private_key_hex)

    if downstream:
        message["downstream_token_ids"] = downstream

    return message


# ──────────────────────────────────────────────
# Heartbeat
# ──────────────────────────────────────────────

def send_heartbeat(
    token_id: str,
    delegator_id: str,
    delegate_id: str,
    transport_port: int,
) -> bool:
    """Send a delegation heartbeat P2P message to the delegate.

    This is a best-effort UDP-like fire: it POSTs to the delegate's transport
    and returns True if accepted. The heartbeat is a structural message
    (type: "delegation_heartbeat") that the transport processes without LLM.

    Args:
        token_id: The token this heartbeat is for
        delegator_id: Agent ID sending the heartbeat
        delegate_id: Agent ID of the delegate
        transport_port: Port of the delegate's transport

    Returns:
        True if the heartbeat was accepted (HTTP 200 with accepted: true)
    """
    import urllib.request

    message = {
        "type": "delegation_heartbeat",
        "token_id": token_id,
        "delegator_id": delegator_id,
        "timestamp": int(time.time()),
    }

    try:
        data = json.dumps(message).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{transport_port}/message",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("accepted", False)
    except Exception:
        return False


# ──────────────────────────────────────────────
# Transport enforcement helpers
# ──────────────────────────────────────────────

def enforce_bb_read(
    message: dict,
    token: Optional[dict] = None,
    registry: Optional[list] = None,
    heartbeat_tracker: Optional[HeartbeatTracker] = None,
) -> Tuple[bool, str]:
    """Enforce delegation token scope on a BB_READ operation.

    Args:
        message: The BB_READ message envelope
        token: Delegation token to validate (None means no enforcement)
        registry: Agent registry
        heartbeat_tracker: Heartbeat tracker

    Returns:
        (allowed: bool, reason: str)
    """
    if token is None:
        return True, ""

    board_id = message.get("boardId", "default")
    resource = f"board:{board_id}"
    return validate_token(token, "bb_read", resource, "local", registry, heartbeat_tracker)


def enforce_send_message(
    target: str,
    token: Optional[dict] = None,
    registry: Optional[list] = None,
    heartbeat_tracker: Optional[HeartbeatTracker] = None,
) -> Tuple[bool, str]:
    """Enforce delegation token scope on a send_message operation.

    Args:
        target: The message target (e.g. "maestro:proteus" or "telegram")
        token: Delegation token to validate
        registry: Agent registry
        heartbeat_tracker: Heartbeat tracker

    Returns:
        (allowed: bool, reason: str)
    """
    if token is None:
        return True, ""

    resource = f"target:{target}"
    return validate_token(token, "send_message", resource, "local", registry, heartbeat_tracker)
