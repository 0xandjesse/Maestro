"""
Checklist tool — hierarchical task delegation for the Swarm Corp agent mesh.

Backed by ~/.maestro/checklists/{checklist_id}.json

Agents create ordered work queues (Checklists), share them read-only with
subordinates, and receive structured completion pings as items finish.
Workers move top-to-bottom automatically — no human prompt between items.
"""
import json
import datetime
import os
import sys

import requests

# Import checklist_manager from the maestro-transport directory
MT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if MT_DIR not in sys.path:
    sys.path.insert(0, MT_DIR)

from checklist_manager import (
    create_checklist,
    read_checklist,
    update_item,
    list_checklists,
    cancel_checklist,
    update_ping,
    get_next_item,
    CL_ROOT,
)

from tools.registry import registry

GATEWAY_PORTS = {
    "songbird": 8648,
    "proteus": 8645,
    "stormtrooper": 8646,
    "hermes": 8641,
    "lexicon": 8643,
    "mnemosyne": 8647,
}
AUTH = "Bearer maestro-local-dev"

MAESTRO_PORTS = {
    "songbird": 3842,
    "proteus": 3846,
    "stormtrooper": 3847,
    "hermes": 3844,
    "lexicon": 3843,
    "mnemosyne": 3845,
}
JESSE_CHAT_ID = "8244638936"


def _send_notify(notify_target: str, checklist_id: str, item_id: str, summary: str, artifacts: list, assigned_to: str):
    """Fire a notification to the target specified on a checklist item.

    notify_target can be:
      - "jesse"      → send_message to Telegram (Jesse's chat)
      - <agent_id>   → Maestro direct message to that agent's transport
    """
    msg = (
        f"✅ Checklist item complete\n"
        f"Checklist: {checklist_id}\n"
        f"Item: {item_id} (completed by {assigned_to})\n"
        f"Summary: {summary or '—'}"
    )
    if artifacts:
        msg += f"\nArtifacts: {', '.join(artifacts)}"

    if notify_target == "jesse":
        # Deliver via the executing agent's gateway send_message
        # Use requests to hit the gateway API directly with a send_message tool call
        import uuid, time
        for port in GATEWAY_PORTS.values():
            try:
                resp = requests.post(
                    f"http://localhost:{port}/v1/chat/completions",
                    headers={"Authorization": AUTH, "Content-Type": "application/json"},
                    json={
                        "model": "hermes-agent",
                        "messages": [{"role": "user", "content":
                            f"Send this message to Jesse on Telegram immediately, no commentary:\n\n{msg}"
                        }],
                        "stream": False,
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    break
            except Exception:
                continue
    else:
        # Maestro direct to agent transport
        port = MAESTRO_PORTS.get(notify_target)
        if not port:
            return
        import uuid, time
        payload = {
            "id": str(uuid.uuid4()),
            "type": "direct",
            "version": "3.2",
            "sender": {"agentId": "checklist"},
            "recipient": notify_target,
            "content": msg,
            "timestamp": int(time.time() * 1000),
            "nonce": str(uuid.uuid4()),
        }
        try:
            requests.post(
                f"http://localhost:{port}/message",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=5,
            )
        except Exception:
            pass


def _send_maestro_ping(owner: str, payload: dict):
    """Send a Maestro completion ping to the owner's gateway."""
    port = GATEWAY_PORTS.get(owner, 8645)
    try:
        requests.post(
            f"http://localhost:{port}/v1/chat/completions",
            headers={"Authorization": AUTH, "Content-Type": "application/json"},
            json={
                "model": "hermes-agent",
                "messages": [{"role": "user", "content": json.dumps(payload)}],
                "stream": False,
            },
            timeout=30,
        )
    except Exception:
        pass


# ── Handlers ──────────────────────────────────────────────────────────────────

def _handle_checklist_create(args, **kw):
    checklist_id = create_checklist(
        created_by=args["created_by"],
        assigned_to=args["assigned_to"],
        title=args["title"],
        items=args["items"],
        require_artifacts=args.get("require_artifacts", False),
        checkin_interval_min=args.get("checkin_interval_min", 30),
        parent_checklist_id=args.get("parent_checklist_id"),
        notify_on_all_items=args.get("notify_on_all_items"),
    )
    return json.dumps({"ok": True, "checklist_id": checklist_id})


def _handle_checklist_read(args, **kw):
    try:
        cl = read_checklist(args["checklist_id"])
        return json.dumps({"ok": True, "checklist": cl})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


def _handle_checklist_update_item(args, **kw):
    result = update_item(
        checklist_id=args["checklist_id"],
        item_id=args["item_id"],
        status=args.get("status"),
        summary=args.get("summary"),
        artifacts=args.get("artifacts"),
        child_checklist_id=args.get("child_checklist_id"),
    )
    return json.dumps(result)


def _handle_checklist_complete_item(args, **kw):
    checklist_id = args["checklist_id"]
    item_id = args["item_id"]
    result_status = args.get("result", "ok")
    summary = args.get("summary", "")
    artifacts = args.get("artifacts", [])

    # Read current state so we only notify on genuine transitions
    cl = read_checklist(checklist_id)
    prev_item = next((i for i in cl.get("items", []) if i.get("id") == item_id), None)
    already_done = prev_item is not None and prev_item.get("status") == "done"
    owner = cl["created_by"]
    assigned_to = cl["assigned_to"]

    # Update the item
    update_result = update_item(
        checklist_id=checklist_id,
        item_id=item_id,
        status="done",
        result=result_status,
        summary=summary,
        artifacts=artifacts,
    )

    # Skip pings if this item was already done — prevents duplicate spam
    if already_done:
        return json.dumps(update_result)

    # Send completion ping to owner
    try:
        payload = {
            "type": "checklist_item_complete",
            "checklist_id": checklist_id,
            "item_id": item_id,
            "result": result_status,
            "summary": summary,
            "artifacts": artifacts or [],
        }
        _send_maestro_ping(owner, payload)
        update_ping(checklist_id)

        # Fire per-item notify if set
        item = next((i for i in cl.get("items", []) if i.get("id") == item_id), None)
        if item and item.get("notify"):
            _send_notify(
                notify_target=item["notify"],
                checklist_id=checklist_id,
                item_id=item_id,
                summary=summary,
                artifacts=artifacts or [],
                assigned_to=assigned_to,
            )
        # Fallback to checklist-level notify_on_all_items
        elif cl.get("notify_on_all_items"):
            _send_notify(
                notify_target=cl["notify_on_all_items"],
                checklist_id=checklist_id,
                item_id=item_id,
                summary=summary,
                artifacts=artifacts or [],
                assigned_to=assigned_to,
            )
    except Exception:
        pass

    return json.dumps(update_result)


def _handle_checklist_list(args, **kw):
    agent_id = args.get("agent_id")
    cls = list_checklists(agent_id=agent_id)
    return json.dumps({"ok": True, "count": len(cls), "checklists": cls})


def _handle_checklist_cancel(args, **kw):
    result = cancel_checklist(args["checklist_id"])
    return json.dumps(result)


# ── Registry ──────────────────────────────────────────────────────────────────

registry.register(
    name="checklist_create",
    toolset="checklist",
    schema={
        "name": "checklist_create",
        "description": "Create a new Checklist (ordered task list) and assign it to an agent. Returns the checklist_id. Only officers can create Checklists (honor system locally). Items are plain string descriptions; they get auto-converted to item dicts with IDs A, B, C, ...",
        "parameters": {
            "type": "object",
            "properties": {
                "created_by": {"type": "string", "description": "Officer creating this checklist (e.g. 'proteus')"},
                "assigned_to": {"type": "string", "description": "Agent responsible for executing this checklist (e.g. 'stormtrooper')"},
                "title": {"type": "string", "description": "Short title for the checklist"},
                "items": {
                    "type": "array",
                    "description": "List of task descriptions in order. Each item can be a plain string, or an object with {description: str, notify: str} where notify is an agent_id or 'jesse' to receive a notification when that item completes.",
                    "items": {"oneOf": [{"type": "string"}, {"type": "object", "properties": {"description": {"type": "string"}, "notify": {"type": "string"}}, "required": ["description"]}]},
                },
                "require_artifacts": {"type": "boolean", "description": "If true, worker MUST include file paths in completion pings", "default": False},
                "checkin_interval_min": {"type": "integer", "description": "Minutes between check-in pings from owner cron. Default: 30", "default": 30},
                "parent_checklist_id": {"type": "string", "description": "Parent checklist ID if this is a sub-delegation. Omit for top-level.", "default": None},
                "notify_on_all_items": {"type": "string", "description": "If set, every item without its own 'notify' field inherits this notification target. Use 'jesse' or an agent_id. Per-item 'notify' overrides this. Omit for no default notifications.", "default": None},
            },
            "required": ["created_by", "assigned_to", "title", "items"],
        },
    },
    handler=_handle_checklist_create,
)

registry.register(
    name="checklist_read",
    toolset="checklist",
    schema={
        "name": "checklist_read",
        "description": "Read a Checklist by ID. Returns the full checklist JSON including item statuses.",
        "parameters": {
            "type": "object",
            "properties": {
                "checklist_id": {"type": "string", "description": "Checklist ID (e.g. 'CL-proteus-a3f9c12b')"},
            },
            "required": ["checklist_id"],
        },
    },
    handler=_handle_checklist_read,
)

registry.register(
    name="checklist_update_item",
    toolset="checklist",
    schema={
        "name": "checklist_update_item",
        "description": "Update one item in a Checklist. Used by the assignee as they work (set status, summary, artifacts, child_checklist_id).",
        "parameters": {
            "type": "object",
            "properties": {
                "checklist_id": {"type": "string", "description": "Checklist ID"},
                "item_id": {"type": "string", "description": "Item ID (e.g. 'A')"},
                "status": {"type": "string", "description": "pending | in_progress | done | blocked"},
                "summary": {"type": "string", "description": "Plain-English summary of what was done or the blocker"},
                "artifacts": {"type": "array", "items": {"type": "string"}, "description": "File paths produced by this item"},
                "child_checklist_id": {"type": "string", "description": "If this item was sub-delegated, the child checklist ID", "default": None},
            },
            "required": ["checklist_id", "item_id"],
        },
    },
    handler=_handle_checklist_update_item,
)

registry.register(
    name="checklist_complete_item",
    toolset="checklist",
    schema={
        "name": "checklist_complete_item",
        "description": "Mark a Checklist item as done and send a Maestro completion ping to the owner. This is the primary way workers report progress. call this after finishing each item, then move to the next item immediately — do not stop and ask what to do next.",
        "parameters": {
            "type": "object",
            "properties": {
                "checklist_id": {"type": "string", "description": "Checklist ID"},
                "item_id": {"type": "string", "description": "Item ID (e.g. 'A')"},
                "result": {"type": "string", "description": "ok | error | blocked", "default": "ok"},
                "summary": {"type": "string", "description": "Plain-English summary of what was accomplished"},
                "artifacts": {"type": "array", "items": {"type": "string"}, "description": "File paths produced by this item"},
            },
            "required": ["checklist_id", "item_id"],
        },
    },
    handler=_handle_checklist_complete_item,
)

registry.register(
    name="checklist_list",
    toolset="checklist",
    schema={
        "name": "checklist_list",
        "description": "List all Checklists where the given agent is either the creator or assignee. If no agent_id is given, list ALL checklists.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID to filter by (created_by or assigned_to). Omit to list all.", "default": None},
            },
            "required": [],
        },
    },
    handler=_handle_checklist_list,
)

registry.register(
    name="checklist_cancel",
    toolset="checklist",
    schema={
        "name": "checklist_cancel",
        "description": "Cancel a Checklist. Only the owner should call this (honor system locally). Sets status to cancelled.",
        "parameters": {
            "type": "object",
            "properties": {
                "checklist_id": {"type": "string", "description": "Checklist ID to cancel"},
            },
            "required": ["checklist_id"],
        },
    },
    handler=_handle_checklist_cancel,
)
