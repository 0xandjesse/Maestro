#!/usr/bin/env python3
"""
Hermes Memory Tool — P2N surface for agent persistent memory.
Direct filesystem access to per-agent memory boards.
"""

import json, time, uuid
from pathlib import Path

BB_ROOT = Path("/home/andjesse/.maestro/blackboards")
OFFICER_WHITELIST = {
    "songbird", "proteus", "lexicon", "hermes", "mnemosyne", "stormtrooper"
}


def _now_ms() -> int:
    return int(time.time() * 1000)


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
        now = _now_ms()
        expired = [
            k for k, v in data.items()
            if v.get("ttl_seconds") and (now - v.get("created_at", 0)) > (v["ttl_seconds"] * 1000)
        ]
        for k in expired:
            del data[k]
        return data
    except Exception:
        return {}


def _save(agent_id: str, data: dict):
    p = _memory_path(agent_id)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _can_access(memory: dict, requester: str) -> bool:
    owner = memory.get("agent_id", "")
    if requester == owner:
        return True
    if requester not in OFFICER_WHITELIST:
        return False
    shared = memory.get("shared_with", [])
    if "*" in shared or requester in shared:
        return True
    return False


def _is_expired(memory: dict, now_ms: int) -> bool:
    ttl = memory.get("ttl_seconds")
    if ttl is None:
        return False
    created = memory.get("created_at", 0)
    return now_ms > created + (ttl * 1000)


def memory_write(
    agent_id: str,
    content,
    tags=None,
    importance=0.5,
    shared_with=None,
    ttl_seconds=None,
    price=0.0,
    requester=None,
):
    """Write a memory for agent_id. Returns {ok, memory_id, size_bytes}."""
    if requester is None:
        requester = agent_id
    if requester != agent_id:
        return {"ok": False, "reason": "forbidden"}
    data = _load(agent_id)
    now = _now_ms()
    mem_id = str(uuid.uuid4())
    entry = {
        "id": mem_id,
        "agent_id": agent_id,
        "content": content,
        "tags": tags or [],
        "importance": importance,
        "created_at": now,
        "updated_at": now,
        "access_count": 0,
        "last_accessed": now,
        "shared_with": shared_with if shared_with is not None else ["*"],
        "ttl_seconds": ttl_seconds,
        "verified": False,
        "price": price,
        "size_bytes": len(json.dumps(content, ensure_ascii=False).encode("utf-8")),
    }
    data[mem_id] = entry
    _save(agent_id, data)
    return {"ok": True, "memory_id": mem_id, "size_bytes": entry["size_bytes"]}


def memory_read(agent_id: str, memory_id: str, requester: str = None):
    """Read a single memory. Returns {ok, memory} or {ok: false, reason}."""
    if requester is None:
        requester = agent_id
    data = _load(agent_id)
    mem = data.get(memory_id)
    if not mem:
        return {"ok": False, "reason": "not_found"}
    if not _can_access(mem, requester):
        return {"ok": False, "reason": "access_denied"}
    mem["access_count"] = mem.get("access_count", 0) + 1
    mem["last_accessed"] = _now_ms()
    _save(agent_id, data)
    return {"ok": True, "memory": mem}


def memory_search(
    agent_id: str,
    query=None,
    tags=None,
    min_importance=None,
    limit=20,
    requester=None,
):
    """Search memories. Returns {ok, results, total}."""
    if requester is None:
        requester = agent_id
    data = _load(agent_id)
    results = []
    for mem in data.values():
        if not _can_access(mem, requester):
            continue
        if tags:
            mem_tags = set(mem.get("tags", []))
            if not all(t in mem_tags for t in tags):
                continue
        if min_importance is not None and mem.get("importance", 0.5) < min_importance:
            continue
        if query:
            q = query.lower()
            content_str = str(mem.get("content", "")).lower()
            tag_str = " ".join(mem.get("tags", [])).lower()
            if q not in content_str and q not in tag_str:
                continue
        results.append(mem)
    results.sort(key=lambda m: (m.get("importance", 0.5), m.get("last_accessed", 0)), reverse=True)
    return {"ok": True, "results": results[:limit], "total": len(results)}


def memory_delete(agent_id: str, memory_id: str = None, prefix: str = None, requester: str = None):
    """Delete a memory by id or prefix. Returns {ok} or {ok: false, reason}."""
    if requester is None:
        requester = agent_id
    if requester != agent_id:
        return {"ok": False, "reason": "forbidden"}
    data = _load(agent_id)
    if memory_id and memory_id in data:
        del data[memory_id]
        _save(agent_id, data)
        return {"ok": True}
    elif prefix:
        keys = [k for k in data if k.startswith(prefix)]
        for k in keys:
            del data[k]
        _save(agent_id, data)
        return {"ok": True, "deleted": len(keys)}
    return {"ok": False, "reason": "not_found"}


def memory_list(agent_id: str, limit=50, requester: str = None):
    """List accessible memories. Returns {ok, memories, count}."""
    if requester is None:
        requester = agent_id
    data = _load(agent_id)
    results = [m for m in data.values() if _can_access(m, requester)]
    results.sort(key=lambda m: m.get("last_accessed", 0), reverse=True)
    return {"ok": True, "memories": results[:limit], "count": len(results)}
