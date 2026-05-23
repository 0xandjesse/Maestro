"""
Shared blackboard tool — P2N key/value boards for cross-agent coordination.
Any officer can read or write any board. No access control — these are shared workspaces.

Backed by ~/.maestro/blackboards/{board}.json
Primary use case: Proteus maintains proteus_work_queue as a rolling to-do list
readable by Songbird at any time without asking.
"""
import datetime
import json
import os
import threading
from pathlib import Path

from tools.registry import registry

BB_ROOT = Path(os.getenv("MAESTRO_BB_ROOT", "/home/andjesse/.maestro/blackboards"))
_lock = threading.Lock()


def _board_path(board: str) -> Path:
    # Sanitize: strip slashes and .json suffix if caller included it
    name = board.strip("/").replace("/", "_")
    if not name.endswith(".json"):
        name = name + ".json"
    return BB_ROOT / name


def _load_board(board: str) -> dict:
    p = _board_path(board)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_board(board: str, data: dict):
    BB_ROOT.mkdir(parents=True, exist_ok=True)
    _board_path(board).write_text(json.dumps(data, indent=2))


def bb_read(board: str, key: str | None = None) -> dict:
    data = _load_board(board)
    if key is not None:
        if key not in data:
            return {"ok": False, "error": f"Key '{key}' not found in board '{board}'"}
        return {"ok": True, "board": board, "key": key, "value": data[key]}
    return {"ok": True, "board": board, "data": data}


def bb_write(board: str, key: str, value) -> dict:
    with _lock:
        data = _load_board(board)
        data[key] = value
        _save_board(board, data)
    return {"ok": True, "board": board, "key": key}


def bb_delete(board: str, key: str) -> dict:
    with _lock:
        data = _load_board(board)
        existed = key in data
        if existed:
            del data[key]
            _save_board(board, data)
    return {"ok": True, "board": board, "key": key, "deleted": existed}


def bb_list() -> dict:
    BB_ROOT.mkdir(parents=True, exist_ok=True)
    boards = [p.stem for p in sorted(BB_ROOT.glob("*.json"))]
    return {"ok": True, "boards": boards, "count": len(boards)}


def _prune_bb(entries: list, hours: int = 4) -> list:
    cutoff = (datetime.datetime.now(datetime.timezone.utc) -
              datetime.timedelta(hours=hours)).isoformat()
    return [e for e in entries if e.get("ts", "") >= cutoff]


def _save_board_raw(board: str, data):
    """Save any JSON-serializable value (not just dicts)."""
    BB_ROOT.mkdir(parents=True, exist_ok=True)
    _board_path(board).write_text(json.dumps(data, indent=2))


def bb_append(board: str, entry: dict) -> dict:
    """Append one entry to an array-format BB board. Prunes entries older than 4h.
    Use for agent activity boards: {agent_id}_bb.json"""
    with _lock:
        p = _board_path(board)
        data = json.loads(p.read_text()) if p.exists() else []
        if not isinstance(data, list):
            data = []
        data.insert(0, entry)  # newest first
        data = _prune_bb(data)
        _save_board_raw(board, data)
    return {"ok": True, "board": board, "count": len(data)}


# ── Handlers ──────────────────────────────────────────────────────────────────

def _handle_bb_read(args, **kw):
    return json.dumps(bb_read(board=args["board"], key=args.get("key")))


def _handle_bb_write(args, **kw):
    return json.dumps(bb_write(board=args["board"], key=args["key"], value=args["value"]))


def _handle_bb_delete(args, **kw):
    return json.dumps(bb_delete(board=args["board"], key=args["key"]))


def _handle_bb_list(args, **kw):
    return json.dumps(bb_list())

def _handle_bb_append(args, **kw):
    return json.dumps(bb_append(board=args["board"], entry=args["entry"]))


# ── Registry ──────────────────────────────────────────────────────────────────

registry.register(
    name="bb_read",
    toolset="agent_memory",
    schema={
        "name": "bb_read",
        "description": "Read a shared blackboard. Returns the full board JSON or a single key. Boards are shared P2N workspaces — any agent can read any board. Example boards: proteus_work_queue, songbird_directives.",
        "parameters": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "Board name (e.g. 'proteus_work_queue'). Do not include .json extension."},
                "key": {"type": "string", "description": "Optional: read a single key from the board. Omit to read the whole board."},
            },
            "required": ["board"],
        },
    },
    handler=_handle_bb_read,
)

registry.register(
    name="bb_write",
    toolset="agent_memory",
    schema={
        "name": "bb_write",
        "description": "Write a key/value pair to a shared blackboard. Creates the board if it doesn't exist. Value can be any JSON type (string, number, array, object).",
        "parameters": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "Board name (e.g. 'proteus_work_queue')"},
                "key": {"type": "string", "description": "Key to write"},
                "value": {"description": "Value to store (any JSON-serializable type)"},
            },
            "required": ["board", "key", "value"],
        },
    },
    handler=_handle_bb_write,
)

registry.register(
    name="bb_delete",
    toolset="agent_memory",
    schema={
        "name": "bb_delete",
        "description": "Delete a key from a shared blackboard.",
        "parameters": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "Board name"},
                "key": {"type": "string", "description": "Key to delete"},
            },
            "required": ["board", "key"],
        },
    },
    handler=_handle_bb_delete,
)

registry.register(
    name="bb_list",
    toolset="agent_memory",
    schema={
        "name": "bb_list",
        "description": "List all shared blackboard names under ~/.maestro/blackboards/.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    handler=_handle_bb_list,
)

registry.register(
    name="bb_append",
    toolset="agent_memory",
    schema={
        "name": "bb_append",
        "description": "Append a plain-English activity entry to an agent BB board. Auto-prunes entries older than 4h. Use {agent_id}_bb as the board name. Call at task_start (status: in_progress) and task_finish (status: done).",
        "parameters": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "Board name, e.g. 'proteus_bb'"},
                "entry": {
                    "type": "object",
                    "description": "Entry to append",
                    "properties": {
                        "ts": {"type": "string", "description": "ISO 8601 UTC timestamp"},
                        "task_id": {"type": "string", "description": "Task ID"},
                        "description": {"type": "string", "description": "Plain English description of what was done"},
                        "status": {"type": "string", "description": "done | in_progress | blocked"},
                        "duration_min": {"type": "number", "description": "How long the task took in minutes (for done entries)"},
                    },
                    "required": ["ts", "description", "status"],
                },
            },
            "required": ["board", "entry"],
        },
    },
    handler=_handle_bb_append,
)
