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
    subject = data.get("subject", "")

    if not agent_id or not content:
        return web.json_response({"ok": False, "reason": "Missing agent_id or content"}, status=400)

    platform = data.get("platform", "telegram")
    if platform != "telegram":
        return web.json_response({"ok": False, "reason": f"Platform {platform} not supported yet"}, status=501)

    async def _send_notification(to_agent_id, header, body, subject="", msg_type="direct", direction="in"):
        """Deliver notification to one agent's Telegram chat. Returns (ok, detail).
        
        direction: "in" for incoming messages (📥), "out" for outgoing (📤).
        """
        display_mode = _get_display_mode(to_agent_id)
        if display_mode == "off":
            return True, "suppressed"
        tcfg = _load_telegram_config(to_agent_id)
        if not tcfg or not tcfg.get("token") or not tcfg.get("chat_id"):
            return False, f"No Telegram config for {to_agent_id}"
        chat_id = tcfg["chat_id"]
        token = tcfg["token"]
        emoji = "📨" if direction == "out" else "📥"
        if display_mode == "short":
            # Compact header + subject only, italicized
            subj = (subject or body[:80])
            subj = subj.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            sender_label = from_agent if direction == "out" else from_agent
            recip_label = to_agent if direction == "out" else to_agent_id
            short_text = f"{emoji} {sender_label} → {recip_label}:\n\n<i>{subj}</i>"
            if len(short_text) <= 4096:
                result = await _send_telegram(token, chat_id, short_text, parse_mode="HTML")
                if result.get("ok"):
                    return True, result.get("message_id")
                return False, result.get("error", "Unknown")
            else:
                short = short_text[:200] + "...\n\n[Full message attached]"
                short_result = await _send_telegram(token, chat_id, short, parse_mode="HTML")
                file_result = await _send_telegram_document(
                    token, chat_id, body.encode("utf-8"),
                    filename=f"maestro_{from_agent}_{msg_type}.txt"
                )
                return (short_result.get("ok") or file_result.get("ok")), "ok"
        # Long mode (default): header + italicized body
        safe_header = header.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        safe_body = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        formatted = f"{safe_header}<i>{safe_body}</i>"
        if len(formatted) <= 4096:
            result = await _send_telegram(token, chat_id, formatted, parse_mode="HTML")
            if result.get("ok"):
                return True, result.get("message_id")
            return False, result.get("error", "Unknown")
        else:
            short = f"{safe_header}<i>{safe_body[:200]}...</i>\n\n[Full message attached]"
            short_result = await _send_telegram(token, chat_id, short, parse_mode="HTML")
            file_result = await _send_telegram_document(
                token, chat_id, body.encode("utf-8"),
                filename=f"maestro_{from_agent}_{msg_type}.txt"
            )
            return (short_result.get("ok") or file_result.get("ok")), "ok"

    # Visibility state loader
    VISIBILITY_PATH = HERMES_HOME / "maestro_visibility.json"

    def _get_display_mode(agent_id: str) -> str:
        """Return 'long' (default), 'short', or 'off' for an agent."""
        if not VISIBILITY_PATH.exists():
            return "long"
        try:
            data = json.loads(VISIBILITY_PATH.read_text())
            if isinstance(data, dict) and agent_id in data:
                return data[agent_id].get("display_mode", "long")
        except Exception:
            pass
        return "long"

    results = []

    # Primary notification — always sent to the agent who owns this transport
    to_agent = data.get("to", "")
    if msg_type == "maestro_out":
        primary_header = f"📤 {from_agent} → {to_agent or from_agent}:\n\n"
    else:
        primary_header = f"📥 {from_agent} → {agent_id}:\n\n"
    primary_ok, primary_detail = await _send_notification(agent_id, primary_header, content, subject=subject, msg_type=msg_type, direction="out" if msg_type == "maestro_out" else "in")
    results.append({"agent": agent_id, "ok": primary_ok, "detail": primary_detail})

    # Secondary notification — mirror to counterparty so both sides see indicators
    # For inbound messages (direct, etc.): also send to the sender so they see delivery
    # For outbound mirrors (maestro_out): also send to the recipient so they see receipt
    counterparty = None
    if msg_type == "maestro_out" and to_agent and to_agent != agent_id:
        counterparty = to_agent
    elif msg_type != "maestro_out" and from_agent != "unknown" and from_agent != agent_id:
        counterparty = from_agent

    if counterparty:
        if msg_type == "maestro_out":
            mirror_header = f"📨 {agent_id} → {counterparty}:\n\n"
        else:
            mirror_header = f"📨 {from_agent} → {agent_id}:\n\n"
        mirror_ok, mirror_detail = await _send_notification(counterparty, mirror_header, content, subject=subject, msg_type=msg_type, direction="in")
        results.append({"agent": counterparty, "ok": mirror_ok, "detail": mirror_detail})

    if any(r["ok"] for r in results):
        return web.json_response({"ok": True, "notifications": results})
    return web.json_response({"ok": False, "reason": results[0]["detail"]}, status=502)


async def _health_handler(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "maestro-gateway-bridge", "version": "0.1"})


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
