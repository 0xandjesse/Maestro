"""Checklist manager — pure Python file I/O for Checklist primitives."""
import json
import datetime
import threading
import uuid
from pathlib import Path

CL_ROOT = Path("/home/andjesse/.maestro/checklists")
_lock = threading.Lock()


def _cl_path(checklist_id: str) -> Path:
    return CL_ROOT / f"{checklist_id}.json"


def _sanitize_id(checklist_id: str) -> str:
    c = checklist_id.strip("/")
    if c.endswith(".json"):
        c = c[:-5]
    return c


def _generate_item_id(items: list) -> str:
    """Generate the next item ID (A, B, C, ... AA, AB, ...)."""
    n = len(items)
    s = ""
    while n >= 0:
        rem = n % 26
        s = chr(ord("A") + rem) + s
        n = n // 26 - 1
    return s


def create_checklist(created_by: str, assigned_to: str, title: str, items: list,
                     require_artifacts: bool = False, checkin_interval_min: int = 30,
                     parent_checklist_id: str = None,
                     notify_on_all_items: str = None) -> str:
    """
    Create a new checklist and return its ID.
    items: list of plain-string descriptions (converted to full item dicts).
    """
    CL_ROOT.mkdir(parents=True, exist_ok=True)
    checklist_id = f"CL-{created_by}-{uuid.uuid4().hex[:8]}"
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    
    item_list = []
    for desc in items:
        item_id = _generate_item_id(item_list)
        # Items can be plain strings or dicts with {description, notify, verify, category, ...}
        if isinstance(desc, dict):
            notify = desc.get("notify")
            description = desc.get("description", str(desc))
            verify = desc.get("verify")
            category = desc.get("category", "general")
        else:
            notify = None
            description = desc
            verify = None
            category = "general"
        item_dict = {
            "id": item_id,
            "description": description,
            "notify": notify,       # agent_id, "jesse", or None
            "status": "pending",
            "started_at": None,
            "completed_at": None,
            "result": None,
            "summary": None,
            "artifacts": [],
            "child_checklist_id": None,
            "category": category,
        }
        if verify is not None:
            item_dict["verify"] = verify
        item_list.append(item_dict)
    
    cl = {
        "id": checklist_id,
        "created_at": now,
        "created_by": created_by,
        "assigned_to": assigned_to,
        "title": title,
        "parent_checklist_id": parent_checklist_id,
        "require_artifacts": bool(require_artifacts),
        "checkin_interval_min": int(checkin_interval_min),
        "notify_on_all_items": notify_on_all_items,
        "status": "active",
        "completed_at": None,
        "last_ping_at": None,
        "items": item_list,
    }
    
    with _lock:
        _cl_path(checklist_id).write_text(json.dumps(cl, indent=2))
    return checklist_id


def read_checklist(checklist_id: str) -> dict:
    checklist_id = _sanitize_id(checklist_id)
    p = _cl_path(checklist_id)
    if not p.exists():
        raise FileNotFoundError(f"Checklist {checklist_id} not found")
    return json.loads(p.read_text())


def update_item(checklist_id: str, item_id: str, **fields) -> dict:
    """Update fields on a checklist item. Thread-safe."""
    checklist_id = _sanitize_id(checklist_id)
    with _lock:
        cl = read_checklist(checklist_id)
        for item in cl.get("items", []):
            if item.get("id") == item_id:
                for k, v in fields.items():
                    if v is not None:
                        item[k] = v
                if fields.get("status") == "done":
                    item["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
                if fields.get("status") == "in_progress":
                    item["started_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
                _cl_path(checklist_id).write_text(json.dumps(cl, indent=2))
                return {"ok": True, "checklist_id": checklist_id, "item_id": item_id, "item": item}
        return {"ok": False, "error": f"Item {item_id} not found in checklist {checklist_id}"}


def list_checklists(agent_id: str = None) -> list:
    """List all checklists, optionally filtering by created_by or assigned_to."""
    CL_ROOT.mkdir(parents=True, exist_ok=True)
    results = []
    for p in sorted(CL_ROOT.glob("*.json")):
        try:
            cl = json.loads(p.read_text())
            if agent_id is None or cl.get("created_by") == agent_id or cl.get("assigned_to") == agent_id:
                results.append(cl)
        except Exception:
            continue
    return results


def cancel_checklist(checklist_id: str) -> dict:
    checklist_id = _sanitize_id(checklist_id)
    with _lock:
        cl = read_checklist(checklist_id)
        cl["status"] = "cancelled"
        _cl_path(checklist_id).write_text(json.dumps(cl, indent=2))
    return {"ok": True, "checklist_id": checklist_id, "status": "cancelled"}


def get_pending_items(checklist_id: str) -> list:
    cl = read_checklist(checklist_id)
    return [i for i in cl.get("items", []) if i.get("status") not in ("done", "blocked")]


def get_next_item(checklist_id: str) -> dict | None:
    for item in get_pending_items(checklist_id):
        return item
    return None


def update_ping(checklist_id: str) -> dict:
    """Update last_ping_at timestamp."""
    checklist_id = _sanitize_id(checklist_id)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    with _lock:
        cl = read_checklist(checklist_id)
        cl["last_ping_at"] = now
        _cl_path(checklist_id).write_text(json.dumps(cl, indent=2))
    return {"ok": True, "checklist_id": checklist_id, "last_ping_at": now}
