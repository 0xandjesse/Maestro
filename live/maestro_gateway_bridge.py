#!/usr/bin/env python3
"""Maestro Gateway Bridge — surfaces Maestro inbound messages to messaging channels.

Standalone HTTP server that receives surface notifications from Maestro transports
and forwards them to an agent's configured messaging platform (Telegram, Discord, etc.).

Usage:
    python maestro_gateway_bridge.py --port 8644

Receives POST /maestro/notify:
    {
        "agent_id": "lexicon",
        "from": "proteus",
        "content": "Deploy staging now",
        "summary": "Deploy staging now",
        "msg_type": "direct"
    }
"""
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

try:
    import aiohttp
    from aiohttp import web, ClientSession, ClientTimeout
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    web = None
    ClientSession = None
    ClientTimeout = None

HERMES_HOME = Path("/home/andjesse/.hermes")
PROFILES_ROOT = HERMES_HOME / "profiles"
VISIBILITY_PATH = HERMES_HOME / "maestro_visibility.json"


def _load_env_value(profile: str, key: str) -> Optional[str]:
    """Read a key=value from a profile's .env file."""
    env_path = PROFILES_ROOT / profile / ".env"
    if not env_path.exists():
        return None
    try:
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line[len(key)+1:].strip()
    except Exception:
        return None
    return None


def _load_telegram_config(agent_id: str) -> Optional[dict]:
    """Parse TELEGRAM_* values from agent profile .env."""
    token = _load_env_value(agent_id, "TELEGRAM_BOT_TOKEN")
    users = _load_env_value(agent_id, "TELEGRAM_ALLOWED_USERS")
    if not token:
        return None
    return {
        "token": token,
        "chat_id": users.split(",")[0] if users else None,
    }


def _load_visibility(agent_id: str) -> dict:
    """Read agent display mode from visibility config.
    Returns dict with 'display_mode' key (long/short/off).
    """
    default = {"display_mode": "long"}
    if not VISIBILITY_PATH.exists():
        return default
    try:
        data = json.loads(VISIBILITY_PATH.read_text())
        agent_cfg = data.get(agent_id, {})
        # New field: display_mode
        mode = agent_cfg.get("display_mode")
        if mode in ("long", "short", "off"):
            return {"display_mode": mode}
        # Legacy fallback: if 'full' boolean existed, use it
        if agent_cfg.get("full") is False:
            return {"display_mode": "short"}
        return default
    except Exception:
        return default


def format_maestro_display(message: dict, mode: str) -> Optional[str]:
    """Format a Maestro message for chat display.
    Returns None if mode is 'off' (suppress notification).
    """
    sender = message.get("from", message.get("sender", "unknown"))
    msg_id = message.get("msg_id", message.get("id", "unknown"))[:8]
    content = message.get("content", "")
    msg_type = message.get("msg_type", "direct")

    subject = content[:80].strip()
    if len(content) > 80:
        subject += "..."

    if mode == "off":
        return None
    elif mode == "short":
        sender = message.get("from", message.get("sender", "unknown"))
        recipient = message.get("to", "")
        icon = "📨" if msg_type == "maestro_out" else "📥"
        subject = message.get("subject", subject) or subject
        return f"{icon} Maestro: {sender} -> {recipient}:\n\n<i>{subject}</i>"
    elif mode == "long":
        sender = message.get("from", message.get("sender", "unknown"))
        recipient = message.get("to", "")
        icon = "📨" if msg_type == "maestro_out" else "📥"
        header = f"{icon} Maestro: {sender} -> {recipient}:"
        body = f"<i>{content}</i>" if content else ""
        return f"{header}\n\n{body}"
    else:
        # Default fallback — long mode
        icon = "📨" if msg_type == "maestro_out" else "📥"
        header = f"{icon} Maestro [{msg_id}] from {sender}:"
        body = f"<i>{content}</i>" if content else ""
        return f"{header}\n\n{body}"


async def _send_telegram(token: str, chat_id: str, text: str, parse_mode: str = "Markdown") -> dict:
    """Send a message via Telegram Bot API."""
    if not ClientSession:
        return {"ok": False, "error": "aiohttp not available"}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        async with ClientSession() as session:
            async with session.post(url, json=payload, timeout=ClientTimeout(total=10)) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return {"ok": True, "message_id": data["result"]["message_id"]}
                return {"ok": False, "error": data.get("description", f"HTTP {resp.status}")}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def _send_telegram_document(token: str, chat_id: str, document_bytes: bytes, filename: str = "message.txt") -> dict:
    """Send a document via Telegram Bot API."""
    if not ClientSession:
        return {"ok": False, "error": "aiohttp not available"}
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    try:
        from aiohttp import FormData
        form = FormData()
        form.add_field("chat_id", str(chat_id))
        form.add_field("document", document_bytes, filename=filename, content_type="text/plain")
        async with ClientSession() as session:
            async with session.post(url, data=form, timeout=ClientTimeout(total=30)) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return {"ok": True, "message_id": data["result"]["message_id"]}
                return {"ok": False, "error": data.get("description", f"HTTP {resp.status}")}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def _notify_handler(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "reason": "Invalid JSON"}, status=400)

    agent_id = data.get("agent_id")
    from_agent = data.get("from", "unknown")
    content = data.get("content", "")
    summary = data.get("summary", content[:200])
    msg_type = data.get("msg_type", "direct")

    if not agent_id or not content:
        return web.json_response({"ok": False, "reason": "Missing agent_id or content"}, status=400)

    # Load display mode for this agent
    visibility = _load_visibility(agent_id)
    mode = visibility.get("display_mode", "long")

    # Always route; only format for display
    display_text = format_maestro_display(data, mode)

    # If display mode is off, still return success — message was routed
    if display_text is None:
        return web.json_response({"ok": True, "displayed": False, "reason": "display_mode=off"})

    # Determine platform (only Telegram for now)
    platform = data.get("platform", "telegram")
    if platform == "telegram":
        tcfg = _load_telegram_config(agent_id)
        if not tcfg or not tcfg.get("token"):
            return web.json_response(
                {"ok": False, "reason": f"No Telegram token for {agent_id}"}, status=404
            )
        chat_id = tcfg["chat_id"]
        if not chat_id:
            return web.json_response(
                {"ok": False, "reason": f"No TELEGRAM_ALLOWED_USERS for {agent_id}"}, status=404
            )

        # Telegram message limit: 4096 chars. If content is long, send as document
        # with a short header; otherwise send inline.
        TELEGRAM_MSG_LIMIT = 4096

        if len(display_text) <= TELEGRAM_MSG_LIMIT:
            # Escape HTML special chars to avoid parse errors in HTML mode
            safe_text = (
                display_text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                # Only escape < and > that are NOT part of our <i>...</i> tags
            )
            # Preserve <i> and </i> tags after blanket escaping
            safe_text = safe_text.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
            result = await _send_telegram(tcfg["token"], chat_id, safe_text, parse_mode="HTML")
            if result["ok"]:
                return web.json_response({"ok": True, "displayed": True, "message_id": result.get("message_id")})
            return web.json_response({"ok": False, "reason": result["error"]}, status=502)
        else:
            # Send short header inline, content as file
            short = (display_text[:200] + "...\n\n[Full message attached]")
            short = (
                short.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            short = short.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
            short_result = await _send_telegram(tcfg["token"], chat_id, short, parse_mode="HTML")
            file_result = await _send_telegram_document(
                tcfg["token"], chat_id, content.encode("utf-8"),
                filename=f"maestro_{from_agent}_{msg_type}.txt"
            )
            if short_result.get("ok") or file_result.get("ok"):
                return web.json_response({"ok": True, "displayed": True})
            return web.json_response({"ok": False, "reason": short_result.get("error") or file_result.get("error")}, status=502)

    return web.json_response({"ok": False, "reason": f"Platform {platform} not supported yet"}, status=501)


async def _health_handler(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "maestro-gateway-bridge", "version": "0.2"})


async def main_async():
    import asyncio
    port = int(os.environ.get("MAESTRO_BRIDGE_PORT", "8644"))
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    if not AIOHTTP_AVAILABLE:
        print("ERROR: pip install aiohttp")
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] [%(name)s] %(message)s',
        datefmt='%H:%M:%S'
    )
    app = web.Application()
    app.router.add_get("/health", _health_handler)
    app.router.add_post("/maestro/notify", _notify_handler)
    print(f"Maestro Gateway Bridge listening on port {port}")
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        await runner.cleanup()


def main():
    import asyncio
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
