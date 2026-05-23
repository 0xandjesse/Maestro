import json
import logging
import os
import asyncio
from pathlib import Path
from typing import Optional

try:
    from aiohttp import web, ClientSession, ClientTimeout
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

HERMES_HOME = Path("/home/andjesse/.hermes")
PROFILES_ROOT = HERMES_HOME / "profiles"
CONTACTS_PATH = Path("/home/andjesse/.maestro/contacts.json")
VISIBILITY_PATH = Path("/home/andjesse/.hermes/maestro_visibility.json")

def _load_env_value(profile: str, key: str) -> Optional[str]:
    env_path = PROFILES_ROOT / profile / ".env"
    if not env_path.exists(): return None
    try:
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key}="): return line[len(key)+1:].strip()
    except Exception: pass
    return None

def _load_telegram_config(agent_id: str) -> Optional[dict]:
    token = _load_env_value(agent_id, "TELEGRAM_BOT_TOKEN")
    users = _load_env_value(agent_id, "TELEGRAM_ALLOWED_USERS")
    if not token: return None
    return {"token": token, "chat_id": users.split(",")[0] if users else None}

def _load_contacts() -> dict:
    """Load contacts.json keyed by agent name (lowercase). Returns {} on any error."""
    try:
        if CONTACTS_PATH.exists():
            with open(CONTACTS_PATH, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {k.lower(): v for k, v in data.items()}
    except Exception:
        pass
    return {}

def resolve_name(agent_id: str) -> str:
    """Resolve an agent_id to its canonical name via contacts.json.
    
    Matches by agent name (key) OR by uid field within entries.
    NEVER silently fall back to 'unknown'. If lookup fails, return the raw
    agent_id so the caller can decide whether to reject or proceed.
    """
    if not agent_id:
        return ""
    contacts = _load_contacts()
    # Direct key match
    entry = contacts.get(agent_id.lower())
    if isinstance(entry, dict):
        return entry.get("name", agent_id)
    # UID match: search all entries
    aid_lower = agent_id.lower()
    for entry in contacts.values():
        if isinstance(entry, dict) and entry.get("uid", "").lower() == aid_lower:
            return entry.get("name", agent_id)
    return agent_id

def resolve_uid(agent_id: str) -> str:
    """Resolve an agent_id to its canonical UID/address."""
    if not agent_id:
        return ""
    contacts = _load_contacts()
    entry = contacts.get(agent_id.lower())
    if isinstance(entry, dict):
        return entry.get("uid", agent_id)
    # UID match fallback
    aid_lower = agent_id.lower()
    for entry in contacts.values():
        if isinstance(entry, dict) and entry.get("uid", "").lower() == aid_lower:
            return entry.get("uid", agent_id)
    return agent_id

def _get_visibility(agent_id: str) -> str:
    """Read visibility mode for an agent from maestro_visibility.json.
    Returns one of: heartbeat, full. Defaults to heartbeat."""
    try:
        if VISIBILITY_PATH.exists():
            with open(VISIBILITY_PATH, "r") as f:
                vis = json.load(f)
            if isinstance(vis, dict) and agent_id.lower() in vis:
                profile_vis = vis[agent_id.lower()]
                if isinstance(profile_vis, dict):
                    # If 'full' is explicitly true, use full mode
                    if profile_vis.get("full", False):
                        return "full"
                    # Legacy: in/out toggles still supported; if either is on,
                    # default visibility stays heartbeat unless full is set
    except Exception:
        pass
    return "heartbeat"

def _load_visibility(agent_id: str) -> dict:
    """Load full visibility profile for an agent. Returns {} on error."""
    try:
        if VISIBILITY_PATH.exists():
            with open(VISIBILITY_PATH, "r") as f:
                vis = json.load(f)
            if isinstance(vis, dict) and agent_id.lower() in vis:
                profile_vis = vis[agent_id.lower()]
                if isinstance(profile_vis, dict):
                    return profile_vis
    except Exception:
        pass
    return {}

def _extract_item_number(content: str) -> str:
    """Extract checklist item identifier from content string."""
    import re
    # Look for patterns like 'Item: B', 'Item C', 'Step 3', etc.
    patterns = [
        r'Item[:\s]+([A-Z0-9]+)',
        r'Step[:\s]+([A-Z0-9]+)',
        r'Item\s+([A-Z0-9]+)',
    ]
    for pat in patterns:
        m = re.search(pat, content)
        if m:
            return m.group(1)
    return "?"

async def _send_telegram(token: str, chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    async with ClientSession() as session:
        async with session.post(url, json=payload, timeout=ClientTimeout(total=10)) as resp:
            return await resp.json()

async def _notify_handler(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "reason": "INVALID_JSON"}, status=400)

    # --- Identity hardening: reject anything without a resolvable sender ---
    raw_sender = data.get("from") or data.get("agent_id")
    sender_name = resolve_name(raw_sender) if raw_sender else ""
    sender_uid = resolve_uid(raw_sender) if raw_sender else ""
    if not sender_uid or sender_uid == "unknown":
        logging.error("REJECTED: Message received without valid sender identity. from=%s agent_id=%s",
                  data.get("from"), data.get("agent_id"))
        return web.json_response({"ok": False, "reason": "SENDER_IDENTITY_MISSING"}, status=400)

    # Resolve target
    target_agent = data.get("to") or data.get("agent_id")
    if not target_agent:
        return web.json_response({"ok": False, "reason": "NO_TARGET"}, status=400)
    target_name = resolve_name(target_agent)

    # Load Telegram configs for BOTH sender and recipient
    sender_tcfg = _load_telegram_config(raw_sender.lower()) if raw_sender else None
    target_tcfg = _load_telegram_config(target_agent.lower())
    if not target_tcfg or not target_tcfg.get("chat_id"):
        return web.json_response({"ok": False, "reason": "CONFIG_MISSING"}, status=404)

    # Determine visibility modes
    vis_mode = data.get("visibility", _get_visibility(target_agent.lower()))
    msg_type = data.get("msg_type", "direct")
    content = data.get("content", "")
    checklist_id = data.get("checklist_id", "")

    # Load checklist visibility for target agent (default False = heartbeat)
    checklist_vis = _load_visibility(target_agent.lower()).get("checklist", False)

    # --- Determine if this is a checklist message ---
    is_checklist = bool(checklist_id) or msg_type.startswith("checklist_")

    # --- Build Maestro standard header (always present, regardless of toggle) ---
    # Format per spec: "📤 Maestro Sent: [Sender] → [Recipient]"
    #                   "📥 Maestro Recv: [Sender] → [Recipient]"
    # Arrow direction is ALWAYS Sender → Recipient
    if msg_type == "maestro_out":
        # Outbound reply — gateway already delivers content directly to user.
        # Bridge shows header-only to avoid double-firing the same text.
        header = f"📤 Maestro Sent: {sender_name} → {target_name}"
        text = header  # always heartbeat for outbound, regardless of toggle
    else:
        header = f"📥 Maestro Recv: {sender_name} → {target_name}"

    # --- Checklist-specific formatting ---
    if is_checklist:
        # Parse explicit checklist msg_types
        if msg_type == "checklist_receipt":
            # Heartbeat: brief plain-English list of items (just descriptions)
            if checklist_vis:
                # Audit mode: full receipt with item list
                items = data.get("items", [])
                item_lines = "\n".join([f"  • {i.get('description', i) if isinstance(i, dict) else i}" for i in items])
                preview = content if len(content) <= 2000 else content[:1997] + "..."
                text = f"📝 Checklist Received: {checklist_id}\n{header}\n---\n{preview}\n\nItems:\n{item_lines}"
            else:
                # Heartbeat mode: header + brief item list only
                items = data.get("items", [])
                item_lines = "\n".join([f"  • {i.get('description', i) if isinstance(i, dict) else i}" for i in items])
                text = f"📝 Checklist Received: {checklist_id}\n{header}\n\nItems:\n{item_lines}"
            await _send_telegram(target_tcfg["token"], target_tcfg["chat_id"], text)
            if sender_tcfg and sender_tcfg.get("chat_id") and sender_tcfg["chat_id"] != target_tcfg["chat_id"]:
                await _send_telegram(sender_tcfg["token"], sender_tcfg["chat_id"], text)
            return web.json_response({"ok": True, "mode": "checklist_receipt", "checklist_id": checklist_id})

        elif msg_type == "checklist_item_done":
            item_id = data.get("item_id", "?")
            if checklist_vis:
                # Audit mode: full details including artifacts, summary
                artifacts = data.get("artifacts", [])
                summary = data.get("summary", "")
                detail = ""
                if summary:
                    detail += f"\nSummary: {summary}"
                if artifacts:
                    detail += f"\nArtifacts: {', '.join(artifacts)}"
                text = f"✅ Completed Step {item_id} {checklist_id}\n{header}{detail}"
            else:
                # Heartbeat mode: minimal
                text = f"✅ Completed Step {item_id} {checklist_id}\n{header}"
            await _send_telegram(target_tcfg["token"], target_tcfg["chat_id"], text)
            if sender_tcfg and sender_tcfg.get("chat_id") and sender_tcfg["chat_id"] != target_tcfg["chat_id"]:
                await _send_telegram(sender_tcfg["token"], sender_tcfg["chat_id"], text)
            return web.json_response({"ok": True, "mode": "checklist_item_done", "checklist_id": checklist_id, "item_id": item_id})

        elif msg_type == "checklist_item_blocked":
            item_id = data.get("item_id", "?")
            reason = data.get("reason", content) or "Unknown blocker"
            if checklist_vis:
                text = f"⚠️ Blocked on Step {item_id} {checklist_id}: {reason}\n{header}"
            else:
                text = f"⚠️ Blocked on Step {item_id} {checklist_id}: {reason}\n{header}"
            await _send_telegram(target_tcfg["token"], target_tcfg["chat_id"], text)
            if sender_tcfg and sender_tcfg.get("chat_id") and sender_tcfg["chat_id"] != target_tcfg["chat_id"]:
                await _send_telegram(sender_tcfg["token"], sender_tcfg["chat_id"], text)
            return web.json_response({"ok": True, "mode": "checklist_item_blocked", "checklist_id": checklist_id, "item_id": item_id})

        elif msg_type == "checklist_complete":
            if checklist_vis:
                preview = content if len(content) <= 3900 else content[:3897] + "..."
                text = f"📝 Checklist Complete: {checklist_id}\n{header}\n---\n{preview}"
            else:
                text = f"📝 Checklist Complete: {checklist_id}\n{header}"
            await _send_telegram(target_tcfg["token"], target_tcfg["chat_id"], text)
            if sender_tcfg and sender_tcfg.get("chat_id") and sender_tcfg["chat_id"] != target_tcfg["chat_id"]:
                await _send_telegram(sender_tcfg["token"], sender_tcfg["chat_id"], text)
            return web.json_response({"ok": True, "mode": "checklist_complete", "checklist_id": checklist_id})

        # Fallback for legacy checklist content strings (heuristic match)
        if "blocked" in content.lower() or "error" in content.lower():
            item_num = _extract_item_number(content)
            if checklist_vis:
                preview = content if len(content) <= 3900 else content[:3897] + "..."
                text = f"⚠️ Blocked on Step {item_num} {checklist_id}: {preview}\n{header}"
            else:
                text = f"⚠️ Blocked on Step {item_num} {checklist_id}\n{header}"
        elif "complete" in content.lower() and "checklist" in content.lower() and "item" not in content.lower():
            if checklist_vis:
                preview = content if len(content) <= 3900 else content[:3897] + "..."
                text = f"📝 Checklist Complete: {checklist_id}\n{header}\n---\n{preview}"
            else:
                text = f"📝 Checklist Complete: {checklist_id}\n{header}"
        elif "received" in content.lower() or ("checklist" in content.lower() and "item" in content.lower()):
            if checklist_vis:
                preview = content if len(content) <= 3900 else content[:3897] + "..."
                text = f"📝 Checklist Received: {checklist_id}\n{header}\n---\n{preview}"
            else:
                text = f"📝 Checklist Received: {checklist_id}\n{header}"
        else:
            item_num = _extract_item_number(content)
            if checklist_vis:
                preview = content if len(content) <= 3900 else content[:3897] + "..."
                text = f"✅ Completed Step {item_num} {checklist_id}\n{header}\n---\n{preview}"
            else:
                text = f"✅ Completed Step {item_num} {checklist_id}\n{header}"

        await _send_telegram(target_tcfg["token"], target_tcfg["chat_id"], text)
        if sender_tcfg and sender_tcfg.get("chat_id") and sender_tcfg["chat_id"] != target_tcfg["chat_id"]:
            await _send_telegram(sender_tcfg["token"], sender_tcfg["chat_id"], text)
        return web.json_response({"ok": True, "mode": "checklist_legacy", "checklist_vis": checklist_vis})

    # --- Calendar creation notification (always visible, bypasses toggle) ---
    elif msg_type == "calendar_created":
        date_time = data.get("date_time", "")
        event_summary = data.get("event_summary", "")
        title = event_summary if event_summary else "Calendar Event"
        lines = [f"🗓️ {title}"]
        lines.append(f"{sender_name} → {target_name}")
        if date_time:
            lines.append(date_time)
        text = "\n".join(lines)
        await _send_telegram(target_tcfg["token"], target_tcfg["chat_id"], text)
        if sender_tcfg and sender_tcfg.get("chat_id") and sender_tcfg["chat_id"] != target_tcfg["chat_id"]:
            await _send_telegram(sender_tcfg["token"], sender_tcfg["chat_id"], text)
        return web.json_response({"ok": True, "mode": "calendar_created"})

    # --- General Maestro message flow (non-checklist, non-outbound-mirror) ---
    text = header  # fallback; branches below overwrite
    if msg_type == "maestro_out":
        # Already handled above: header-only, no double-fire
        res = await _send_telegram(target_tcfg["token"], target_tcfg["chat_id"], text)
    elif vis_mode == "full":
        preview = content if len(content) <= 3900 else content[:3897] + "..."
        text = f"{header}\n---\n{preview}"
        res = await _send_telegram(target_tcfg["token"], target_tcfg["chat_id"], text)
    else:
        # Heartbeat: header only, no content, no UIDs
        text = header
        res = await _send_telegram(target_tcfg["token"], target_tcfg["chat_id"], text)
    ok = res.get("ok", False)

    # Also notify the sender (if different chat_id and config available)
    if sender_tcfg and sender_tcfg.get("chat_id") and sender_tcfg["chat_id"] != target_tcfg["chat_id"]:
        await _send_telegram(sender_tcfg["token"], sender_tcfg["chat_id"], text)

    return web.json_response({"ok": ok, "telegram": res, "mode": vis_mode})

async def _health_handler(request: web.Request) -> web.Response:
    return web.json_response({
        "ok": True,
        "service": "maestro-gateway-bridge",
        "version": "2.2",
        "identity_resolution": "contacts.json"
    })

async def main():
    app = web.Application()
    app.router.add_get("/health", _health_handler)
    app.router.add_post("/maestro/notify", _notify_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8644)
    await site.start()
    logging.info("Maestro gateway bridge listening on 127.0.0.1:8644")
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
