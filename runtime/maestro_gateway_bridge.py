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


def _strip_maestro_wrapper(body: str) -> str:
    """Remove agent-generated Maestro Protocol wrappers from the body.

    Agents tend to prefix their output with:
      [Maestro Protocol — Outbound to ...]
      [Maestro Protocol — Inbound ...]
      etc.

    This strips those lines so the bridge only delivers the actual content.
    """
    lines = body.split("\n")
    if lines and re.match(r'^\[Maestro Protocol', lines[0].strip()):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines).strip()


async def _notify_handler(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "reason": "Invalid JSON"}, status=400)

    agent_id = data.get("agent_id")
    from_agent = data.get("from", "unknown")
    content = data.get("content", "")
    msg_type = data.get("msg_type", "direct")
    subject = data.get("subject", "")

    if not agent_id or not content:
        return web.json_response({"ok": False, "reason": "Missing agent_id or content"}, status=400)

    # Strip agent-generated wrappers from the body
    content = _strip_maestro_wrapper(content)

    platform = data.get("platform", "telegram")
    if platform != "telegram":
        return web.json_response({"ok": False, "reason": f"Platform {platform} not supported yet"}, status=501)

    # Visibility state
    VISIBILITY_PATH = HERMES_HOME / "maestro_visibility.json"

    def _get_display_mode(agent: str) -> str:
        if not VISIBILITY_PATH.exists():
            return "long"
        try:
            v = json.loads(VISIBILITY_PATH.read_text())
            if isinstance(v, dict) and agent in v:
                return v[agent].get("display_mode", "long")
        except Exception:
            pass
        return "long"

    async def _deliver(to_agent: str, emoji: str, header: str, body: str) -> tuple:
        """Deliver a formatted notification to one agent. Returns (ok, detail)."""
        mode = _get_display_mode(to_agent)
        if mode == "off":
            return True, "suppressed"

        tcfg = _load_telegram_config(to_agent)
        if not tcfg or not tcfg.get("token") or not tcfg.get("chat_id"):
            return False, f"No Telegram config for {to_agent}"
        chat_id = tcfg["chat_id"]
        token = tcfg["token"]

        # HTML-safe
        safe_header = header.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        if mode == "short":
            raw_subj = (subject or body[:80])
            if raw_subj.lower().startswith("subject:"):
                raw_subj = raw_subj[8:].strip()
            subj = raw_subj.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            text = f"{emoji} {safe_header}\n\n<i>{subj}</i>"
        else:
            clean_body = body
            if clean_body.lower().startswith("subject:"):
                nl = clean_body.find("\n")
                if nl >= 0:
                    clean_body = clean_body[nl+1:].strip()
                else:
                    clean_body = ""
            safe_body = clean_body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            text = f"{emoji} {safe_header}\n\n<i>{safe_body}</i>"

        if len(text) <= 4096:
            result = await _send_telegram(token, chat_id, text, parse_mode="HTML")
            if result.get("ok"):
                return True, result.get("message_id")
            return False, result.get("error", "Unknown")

        short_text = f"{emoji} {safe_header}<i>{body[:200]}...</i>\n\n[Full message attached]"
        short_result = await _send_telegram(token, chat_id, short_text, parse_mode="HTML")
        file_result = await _send_telegram_document(
            token, chat_id, body.encode("utf-8"),
            filename=f"maestro_{from_agent}_{msg_type}.txt"
        )
        return (short_result.get("ok") or file_result.get("ok")), "ok"

    results = []
    to_agent = data.get("to", "")

    is_outbound = (msg_type == "maestro_out")
    counterparty = None
    if is_outbound and to_agent and to_agent != agent_id:
        counterparty = to_agent
    elif not is_outbound and from_agent != "unknown" and from_agent != agent_id:
        counterparty = from_agent

    if is_outbound:
        primary_emoji = "📨"
        primary_header = f"Maestro direct to {to_agent or from_agent}:"
    else:
        primary_emoji = "📥"
        primary_header = f"Maestro direct from {from_agent}:"
    primary_ok, primary_detail = await _deliver(agent_id, primary_emoji, primary_header, content)
    results.append({"agent": agent_id, "ok": primary_ok, "detail": primary_detail})

    if counterparty:
        if is_outbound:
            mirror_emoji = "📥"
            mirror_header = f"Maestro direct from {from_agent}:"
        else:
            mirror_emoji = "📨"
            mirror_header = f"Maestro direct to {agent_id}:"
        mirror_ok, mirror_detail = await _deliver(counterparty, mirror_emoji, mirror_header, content)
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
