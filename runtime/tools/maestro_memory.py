"""
Maestro Memory Tool — Hermes gateway surface for agent persistent memory.

Wraps the memory engine in maestro-transport/hermes_memory.py and exposes
memory_write, memory_read, memory_search, memory_delete, and memory_list as
Hermes tools so any agent can call them.

Backed by ~/.maestro/blackboards/memory_{agent_id}.json
"""

import json
import sys
from pathlib import Path

from tools.registry import registry

# Ensure maestro-transport is importable
sys.path.insert(0, str(Path.home() / "maestro-transport"))

try:
    from hermes_memory import (
        memory_delete,
        memory_list,
        memory_read,
        memory_search,
        memory_write,
    )
except Exception:
    # Fallback stubs so the module always loads even if maestro-transport is absent
    def _no_op(*a, **kw):
        return {"ok": False, "reason": "hermes_memory unavailable"}

    memory_write = memory_read = memory_search = memory_delete = memory_list = _no_op


# ── Helpers ───────────────────────────────────────────────────────────────────

def _as_json(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False)


# ── Schemas ───────────────────────────────────────────────────────────────────

_MEMORY_WRITE_SCHEMA = {
    "type": "object",
    "description": "Write a persistent memory entry for an agent.",
    "properties": {
        "agent_id": {
            "type": "string",
            "description": "Target agent ID (owner of the memory).",
        },
        "content": {
            "description": "Arbitrary content to store (string, dict, list).",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional tags for filtering.",
        },
        "importance": {
            "type": "number",
            "description": "Importance score 0.0-1.0. Defaults 0.5.",
        },
        "shared_with": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Agent IDs that may read this entry. Use [\"*\"] for all officers.",
        },
        "ttl_seconds": {
            "type": "integer",
            "description": "Optional TTL in seconds.",
        },
        "price": {
            "type": "number",
            "description": "Optional price metadata.",
        },
    },
    "required": ["agent_id", "content"],
}

_MEMORY_READ_SCHEMA = {
    "type": "object",
    "description": "Read a single memory entry by its ID.",
    "properties": {
        "agent_id": {"type": "string", "description": "Agent ID that owns the memory."},
        "memory_id": {"type": "string", "description": "UUID of the memory entry."},
    },
    "required": ["agent_id", "memory_id"],
}

_MEMORY_SEARCH_SCHEMA = {
    "type": "object",
    "description": "Search an agent's memories.",
    "properties": {
        "agent_id": {"type": "string", "description": "Agent ID that owns the memories."},
        "query": {"type": "string", "description": "Substring query (searches content + tags)."},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Require all listed tags.",
        },
        "min_importance": {
            "type": "number",
            "description": "Minimum importance score.",
        },
        "limit": {
            "type": "integer",
            "description": "Max results to return. Default 20.",
        },
    },
    "required": ["agent_id"],
}

_MEMORY_DELETE_SCHEMA = {
    "type": "object",
    "description": "Delete a memory entry by ID.",
    "properties": {
        "agent_id": {"type": "string", "description": "Agent ID that owns the memory."},
        "memory_id": {"type": "string", "description": "UUID of the memory to delete."},
    },
    "required": ["agent_id", "memory_id"],
}

_MEMORY_LIST_SCHEMA = {
    "type": "object",
    "description": "List accessible memories for an agent.",
    "properties": {
        "agent_id": {"type": "string", "description": "Agent ID that owns the memories."},
        "limit": {
            "type": "integer",
            "description": "Max entries to return. Default 50.",
        },
    },
    "required": ["agent_id"],
}


# ── Handlers ──────────────────────────────────────────────────────────────────

def _handle_memory_write(args: dict, **kw) -> str:
    result = memory_write(
        agent_id=args["agent_id"],
        content=args["content"],
        tags=args.get("tags"),
        importance=args.get("importance", 0.5),
        shared_with=args.get("shared_with"),
        ttl_seconds=args.get("ttl_seconds"),
        price=args.get("price", 0.0),
        requester=args["agent_id"],
    )
    return _as_json(result)


def _handle_memory_read(args: dict, **kw) -> str:
    result = memory_read(
        agent_id=args["agent_id"],
        memory_id=args["memory_id"],
        requester=args["agent_id"],
    )
    return _as_json(result)


def _handle_memory_search(args: dict, **kw) -> str:
    result = memory_search(
        agent_id=args["agent_id"],
        query=args.get("query"),
        tags=args.get("tags"),
        min_importance=args.get("min_importance"),
        limit=args.get("limit", 20),
        requester=args["agent_id"],
    )
    return _as_json(result)


def _handle_memory_delete(args: dict, **kw) -> str:
    result = memory_delete(
        agent_id=args["agent_id"],
        memory_id=args["memory_id"],
        requester=args["agent_id"],
    )
    return _as_json(result)


def _handle_memory_list(args: dict, **kw) -> str:
    result = memory_list(
        agent_id=args["agent_id"],
        limit=args.get("limit", 50),
        requester=args["agent_id"],
    )
    return _as_json(result)


# ── Registration ──────────────────────────────────────────────────────────────

registry.register(
    name="memory_write",
    toolset="maestro_memory",
    schema=_MEMORY_WRITE_SCHEMA,
    handler=_handle_memory_write,
    description="Write a persistent memory entry for an agent.",
    emoji="🧠",
)

registry.register(
    name="memory_read",
    toolset="maestro_memory",
    schema=_MEMORY_READ_SCHEMA,
    handler=_handle_memory_read,
    description="Read a single memory entry by ID.",
    emoji="🔍",
)

registry.register(
    name="memory_search",
    toolset="maestro_memory",
    schema=_MEMORY_SEARCH_SCHEMA,
    handler=_handle_memory_search,
    description="Search an agent's memories by query and tags.",
    emoji="🔎",
)

registry.register(
    name="memory_delete",
    toolset="maestro_memory",
    schema=_MEMORY_DELETE_SCHEMA,
    handler=_handle_memory_delete,
    description="Delete a memory entry by ID.",
    emoji="🗑️",
)

registry.register(
    name="memory_list",
    toolset="maestro_memory",
    schema=_MEMORY_LIST_SCHEMA,
    handler=_handle_memory_list,
    description="List accessible memories for an agent.",
    emoji="📋",
)
