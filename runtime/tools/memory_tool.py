"""
Persistent agent memory tool — cross-session key/value store per agent.
Backed by ~/.maestro/blackboards/memory_{agent_id}.json
Accessible P2N: any officer can read another's shared memories.
"""
import json
import os
import sys
import time
import uuid
import threading
from pathlib import Path
from tools.registry import registry

BB_ROOT = Path(os.getenv("MAESTRO_BB_ROOT", "/home/andjesse/.maestro/blackboards"))
OFFICER_WHITELIST = {"songbird", "proteus", "lexicon", "hermes", "mnemosyne", "stormtrooper"}
_lock = threading.Lock()


def _agent_id_from_env() -> str:
    """Derive the agent ID from the environment so calls without explicit agent_id still work."""
    # Strategy A: HERMES_PROFILE or HERMES_PROFILE_NAME env var
    for env_key in ("HERMES_PROFILE", "HERMES_PROFILE_NAME"):
        candidate = os.environ.get(env_key)
        if candidate and candidate != "unknown":
            return candidate
    # Strategy B: Derive from HERMES_HOME path
    home = os.environ.get("HERMES_HOME", "")
    if home:
        name = Path(home).name
        if name and name != "unknown":
            return name
    # Fallback: never return "unknown" — that produces untraceable memory entries
    return "anonymous"


def _memory_path(agent_id: str) -> Path:
    return BB_ROOT / f"memory_{agent_id}.json"


def _load(agent_id: str) -> dict:
    p = _memory_path(agent_id)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, dict):
            return {}
        now_ms = int(time.time() * 1000)
        expired = [
            k for k, v in data.items()
            if isinstance(v, dict) and v.get("ttl_seconds")
            and (now_ms - v.get("created_at", 0)) > (v["ttl_seconds"] * 1000)
        ]
        for k in expired:
            del data[k]
        if expired:
            _save(agent_id, data)
        return data
    except Exception:
        return {}


def _save(agent_id: str, data: dict):
    BB_ROOT.mkdir(parents=True, exist_ok=True)
    _memory_path(agent_id).write_text(json.dumps(data, indent=2))


def _can_read(agent_id: str, key: str, data: dict, requester: str) -> bool:
    if requester == agent_id:
        return True
    entry = data.get(key, {})
    if not isinstance(entry, dict):
        return False
    shared = entry.get("shared_with", [])
    return "*" in shared or requester in shared


def memory_write(agent_id: str, key: str, value, shared_with=None, importance=0.5,
                 tags=None, ttl_seconds=None) -> dict:
    with _lock:
        data = _load(agent_id)
        now_ms = int(time.time() * 1000)
        existing = data.get(key, {})
        data[key] = {
            "value": value,
            "agent_id": agent_id,
            "shared_with": shared_with or [],
            "importance": float(importance),
            "tags": tags or [],
            "ttl_seconds": ttl_seconds,
            "created_at": existing.get("created_at", now_ms) if isinstance(existing, dict) else now_ms,
            "updated_at": now_ms,
        }
        _save(agent_id, data)
    return {"ok": True, "key": key, "agent_id": agent_id}


def memory_read(agent_id: str, key: str, requester=None) -> dict:
    requester = requester or agent_id
    data = _load(agent_id)
    if key not in data:
        return {"ok": False, "error": f"Key '{key}' not found in {agent_id}'s memory"}
    if not _can_read(agent_id, key, data, requester):
        return {"ok": False, "error": f"Access denied: {requester} cannot read {agent_id}.{key}"}
    return {"ok": True, "key": key, "agent_id": agent_id, "entry": data[key]}


def memory_search(agent_id: str, query: str, requester=None) -> dict:
    requester = requester or agent_id
    data = _load(agent_id)
    q = query.lower()
    results = []
    for k, v in data.items():
        if not _can_read(agent_id, k, data, requester):
            continue
        haystack = k.lower() + " " + json.dumps(v).lower()
        if q in haystack:
            results.append({"key": k, "entry": v})
    return {"ok": True, "agent_id": agent_id, "query": query, "results": results}


def memory_delete(agent_id: str, key: str) -> dict:
    with _lock:
        data = _load(agent_id)
        if key in data:
            del data[key]
            _save(agent_id, data)
            return {"ok": True, "key": key, "deleted": True}
    return {"ok": True, "key": key, "deleted": False}


def memory_list(agent_id: str, requester=None) -> dict:
    requester = requester or agent_id
    data = _load(agent_id)
    keys = [k for k in data if _can_read(agent_id, k, data, requester)]
    return {"ok": True, "agent_id": agent_id, "keys": keys, "count": len(keys)}


# ── Tool handlers ──────────────────────────────────────────────────────────────

def _safe_required(args, field):
    if field not in args:
        return None, json.dumps({"ok": False, "error": f"Missing required parameter: {field}"})
    return args[field], None


def _handle_memory_write(args, **kw):
    agent_id = _agent_id_from_env()
    key, err = _safe_required(args, "key")
    if err:
        return err
    value, err = _safe_required(args, "value")
    if err:
        return err
    assert key is not None
    assert value is not None
    return json.dumps(memory_write(
        agent_id=agent_id,
        key=key,
        value=value,
        shared_with=args.get("shared_with", []),
        importance=args.get("importance", 0.5),
        tags=args.get("tags", []),
        ttl_seconds=args.get("ttl_seconds"),
    ))


def _handle_memory_read(args, **kw):
    agent_id = _agent_id_from_env()
    key, err = _safe_required(args, "key")
    if err:
        return err
    assert key is not None
    return json.dumps(memory_read(
        agent_id=args.get("agent_id", agent_id),
        key=key,
        requester=args.get("requester", agent_id),
    ))


def _handle_memory_search(args, **kw):
    agent_id = _agent_id_from_env()
    query, err = _safe_required(args, "query")
    if err:
        return err
    assert query is not None
    return json.dumps(memory_search(
        agent_id=args.get("agent_id", agent_id),
        query=query,
        requester=args.get("requester", agent_id),
    ))


def _handle_memory_delete(args, **kw):
    agent_id = _agent_id_from_env()
    key, err = _safe_required(args, "key")
    if err:
        return err
    assert key is not None
    return json.dumps(memory_delete(agent_id=agent_id, key=key))


def _handle_memory_list(args, **kw):
    agent_id = _agent_id_from_env()
    return json.dumps(memory_list(
        agent_id=args.get("agent_id", agent_id),
        requester=args.get("requester", agent_id),
    ))


# ── Registry ───────────────────────────────────────────────────────────────────

registry.register(
    name="memory_write",
    toolset="memory",
    schema={
        "name": "memory_write",
        "description": "Write a value to this agent's persistent memory. Survives gateway restarts. Can be shared with specific officers or all ('*').",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Unique memory key for this agent"},
                "value": {"description": "Value to store (any JSON-serializable type)"},
                "shared_with": {"type": "array", "items": {"type": "string"},
                                "description": "Agent IDs that can read this entry, or ['*'] for all officers. Default: private."},
                "importance": {"type": "number", "description": "0.0-1.0 importance score. Higher = kept longer during pruning."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for search/filtering"},
                "ttl_seconds": {"type": "number", "description": "Auto-expire after N seconds. Null = no expiry."},
            },
            "required": ["key", "value"],
        },
    },
    handler=_handle_memory_write,
)

registry.register(
    name="memory_read",
    toolset="memory",
    schema={
        "name": "memory_read",
        "description": "Read a value from any agent's persistent memory. Access controlled by shared_with field.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent whose memory to read (e.g. 'proteus', 'songbird')"},
                "key": {"type": "string", "description": "Memory key to read"},
                "requester": {"type": "string", "description": "Override requester ID for access control. Defaults to self."},
            },
            "required": ["agent_id", "key"],
        },
    },
    handler=_handle_memory_read,
)

registry.register(
    name="memory_search",
    toolset="memory",
    schema={
        "name": "memory_search",
        "description": "Search an agent's persistent memory. Searches keys, values, and tags. Returns all accessible matching entries.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent whose memory to search"},
                "query": {"type": "string", "description": "Search query string"},
                "requester": {"type": "string", "description": "Override requester ID for access control."},
            },
            "required": ["agent_id", "query"],
        },
    },
    handler=_handle_memory_search,
)

registry.register(
    name="memory_delete",
    toolset="memory",
    schema={
        "name": "memory_delete",
        "description": "Delete a key from this agent's own persistent memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Memory key to delete"},
            },
            "required": ["key"],
        },
    },
    handler=_handle_memory_delete,
)

registry.register(
    name="memory_list",
    toolset="memory",
    schema={
        "name": "memory_list",
        "description": "List all accessible memory keys for an agent.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent whose memory to list. Defaults to self."},
                "requester": {"type": "string", "description": "Override requester ID for access control."},
            },
            "required": [],
        },
    },
    handler=_handle_memory_list,
)
