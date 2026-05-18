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

        text = f"📨 *Maestro {msg_type}* from `{from_agent}`:\n_{summary}_"
        result = await _send_telegram(tcfg["token"], chat_id, text)
        if result["ok"]:
            return web.json_response({"ok": True, "message_id": result.get("message_id")})
        return web.json_response({"ok": False, "reason": result["error"]}, status=502)

    return web.json_response({"ok": False, "reason": f"Platform {platform} not supported yet"}, status=501)


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
