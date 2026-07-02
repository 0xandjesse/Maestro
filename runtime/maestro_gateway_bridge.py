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
import asyncio
import json
import logging
import os
import re
import sys
import time
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
REGISTRY_PATH = Path("/home/andjesse/.maestro/registry.json")

# ── Master Vault integration ──
_vault_instance = None
_vault_warned = False  # one-time deprecation warning

# ── Subject dedup ──
_last_subject_by_sender: dict[str, str] = {}


def _get_vault():
    """Lazy-load the Master Vault singleton."""
    global _vault_instance
    if _vault_instance is None:
        try:
            from vault import MasterVault
            _vault_instance = MasterVault()
        except Exception:
            return None
    return _vault_instance


def _load_registry() -> list:
    """Load the Maestro registry file."""
    if not REGISTRY_PATH.exists():
        return []
    try:
        return json.loads(REGISTRY_PATH.read_text())
    except Exception:
        return []


def _resolve_transport_endpoint(agent_id: str) -> Optional[str]:
    """Look up an agent's transport endpoint — vault first, then registry."""
    vault = _get_vault()
    if vault:
        try:
            ports = vault.get_ports(agent_id)
            return f"http://127.0.0.1:{ports['transport']}/message"
        except Exception:
            pass  # fall through to registry
    for agent in _load_registry():
        if agent.get("agentId") == agent_id:
            return agent.get("webhookEndpoint")
    return None


async def _deliver_via_transport(agent_id: str, from_agent: str, content: str,
                                  msg_type: str = "direct", subject: str = "") -> tuple:
    """Fallback delivery: POST directly to an agent's Maestro transport endpoint.
    
    Used when an agent has no Telegram config (Maestro-only agents like Rosetta).
    Returns (ok, detail) tuple consistent with _deliver.
    """
    endpoint = _resolve_transport_endpoint(agent_id)
    if not endpoint:
        return False, f"Agent '{agent_id}' not in registry — no Telegram and no transport"
    if not ClientSession:
        return False, "aiohttp not available for P2N fallback"

    import uuid
    msg_id = f"{from_agent}-{uuid.uuid4().hex[:8]}"
    delivery_payload = {
        "id": msg_id, "type": msg_type,
        "sender": {"agentId": from_agent}, "recipient": agent_id,
        "content": content, "subject": subject,
    }
    try:
        async with ClientSession() as session:
            async with session.post(endpoint, json=delivery_payload,
                                    timeout=ClientTimeout(total=10)) as resp:
                result = await resp.json()
                if result.get("accepted", False):
                    return True, "transport_delivered"
                return False, result.get("reason", "Transport rejected")
    except Exception as e:
        return False, f"P2N fallback failed: {type(e).__name__}: {e}"

def _load_env_value(profile: str, key: str) -> Optional[str]:
    """Read a key=value from a profile's .env file.

    DEPRECATED: Use Master Vault instead. This function emits a one-time
    warning per process lifetime.
    """
    global _vault_warned
    if not _vault_warned:
        _vault_warned = True
        logging.getLogger(__name__).warning(
            "DEPRECATION: Config read from .env (key=%s). Migrate to Master Vault "
            "for unified config. See: python vault_cli.py --help", key,
        )
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
    """Load Telegram config — vault first, then .env fallback."""
    # Try vault first
    vault = _get_vault()
    if vault:
        try:
            token = vault.get_token(agent_id)
            # Get chat_id from vault config or .env
            chat_id = None
            config = vault.get_config(agent_id)
            if config.get("home_channel_id"):
                chat_id = config["home_channel_id"]
            return {"token": token, "chat_id": chat_id}
        except Exception:
            pass  # fall through to .env

    # Fallback: .env
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


async def _notify_sender_error(sender_id: str, error_text: str, intended_recipient: str = ""):
    """Deliver a rejection error to the sender via Telegram ONLY — NOT the transport.

    We route through Telegram (not P2N transport) because sending the error
    back to the transport creates an infinite loop: transport feeds error to LLM →
    LLM replies (still no Subject) → bridge rejects again → transport feeds error →
    ∞. Telegram delivery breaks the cycle: the agent sees the error in TG but it
    never re-enters the LLM processing pipeline.
    """
    tcfg = _load_telegram_config(sender_id)
    if tcfg and tcfg.get("token") and tcfg.get("chat_id"):
        try:
            text = (
                f"📥 Your message to {intended_recipient or 'unknown'} was rejected: "
                f"missing Subject line.\n\n"
                f"Maestro messages MUST start with 'Subject: ...' on the first line.\n"
                f"Please re-send with a Subject line."
            )
            await _send_telegram(tcfg["token"], tcfg["chat_id"], text, parse_mode="HTML")
        except Exception:
            pass


def _should_suppress(sender_id: str, subject: str) -> bool:
    """Suppress if this sender's last delivered message had the same subject."""
    last = _last_subject_by_sender.get(sender_id)
    if last == subject:
        return True
    _last_subject_by_sender[sender_id] = subject
    return False


async def _notify_handler(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "reason": "Invalid JSON"}, status=400)

    agent_id = data.get("agent_id")
    from_agent = data.get("from") or data.get("sender", {}).get("agentId") or "unknown"
    content = data.get("content", "")
    msg_type = data.get("msg_type", "direct")
    subject = data.get("subject", "")

    if not agent_id or not content:
        return web.json_response({"ok": False, "reason": "Missing agent_id or content"}, status=400)

    # ── Subject line enforcement ──
    # Every Maestro message MUST have a Subject line as the first line of content.
    if not subject:
        if content.startswith("Subject:"):
            nl = content.find("\n")
            subject = content[len("Subject:"):nl].strip() if nl > 0 else content[len("Subject:"):].strip()
        else:
            # ── Surface error to the SENDER, not the recipient ──
            # The 400 goes back to the caller, but the sender agent never sees it.
            # Deliver the error directly to the sender's Telegram so they learn.
            sender_err_text = f"📥 Message rejected — missing Subject line\n\nYour message to {agent_id} was rejected by the Maestro bridge: no Subject: line. All Maestro messages must start with 'Subject: ...' on the first line. Please re-send."
            asyncio.create_task(_notify_sender_error(from_agent, sender_err_text, agent_id))
            return web.json_response(
                {"ok": False, "reason": "Missing Subject line. All Maestro messages require 'Subject: ...' as the first line of content. The sender has been notified."},
                status=400,
            )

    # Strip agent-generated wrappers from the body
    content = _strip_maestro_wrapper(content)

    # ── Subject dedup ──
    # Fallback: if no Subject line, use first ~80 chars of body
    dedup_subject = subject.strip() if subject else content[:80].strip()
    if _should_suppress(from_agent, dedup_subject):
        logging.getLogger(__name__).info(
            "Bridge dedup: dropping message from %s (reason: same_subject)", from_agent
        )
        return web.json_response({"ok": False, "reason": "same_subject"}, status=200)

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
            # P2N fallback: no Telegram config — route via transport
            return await _deliver_via_transport(to_agent, from_agent, content, msg_type, subject)
        chat_id = tcfg["chat_id"]
        token = tcfg["token"]

        # HTML-safe
        safe_header = header.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        if mode == "short":
            text = f"{emoji} {safe_header}"
        else:
            clean_body = body
            if clean_body.lower().startswith("subject:"):
                nl = clean_body.find("\n")
                if nl >= 0:
                    clean_body = clean_body[nl+1:].strip()
                else:
                    clean_body = ""
            if clean_body:
                safe_body = clean_body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                text = f"{emoji} {safe_header}\n\n<pre>{safe_body}</pre>"
            else:
                text = f"{emoji} {safe_header}"

        if len(text) <= 4096:
            result = await _send_telegram(token, chat_id, text, parse_mode="HTML")
            if result.get("ok"):
                return True, result.get("message_id")
            # P2N fallback on Telegram API failure
            return await _deliver_via_transport(to_agent, from_agent, content, msg_type, subject)

        short_text = f"{emoji} {safe_header}<i>{body[:200]}...</i>\n\n[Full message attached]"
        short_result = await _send_telegram(token, chat_id, short_text, parse_mode="HTML")
        file_result = await _send_telegram_document(
            token, chat_id, body.encode("utf-8"),
            filename=f"maestro_{from_agent}_{msg_type}.txt"
        )
        if short_result.get("ok") or file_result.get("ok"):
            return True, "ok"
        # P2N fallback on Telegram API failure (long message)
        return await _deliver_via_transport(to_agent, from_agent, content, msg_type, subject)

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
        primary_header = f"To {counterparty or to_agent or 'unknown'}: {subject}"
    else:
        primary_emoji = "📥"
        primary_header = f"From {counterparty or from_agent}: {subject}"
    primary_ok, primary_detail = await _deliver(agent_id, primary_emoji, primary_header, content)
    results.append({"agent": agent_id, "ok": primary_ok, "detail": primary_detail})

    # Only mirror to counterparty if they have a different Telegram chat
    primary_cfg = _load_telegram_config(agent_id)
    primary_chat_id = primary_cfg.get("chat_id") if primary_cfg else None

    if counterparty:
        cp_cfg = _load_telegram_config(counterparty)
        cp_chat_id = cp_cfg.get("chat_id") if cp_cfg else None
        # Deliver mirror if: different chat, OR same chat but different bot token
        # (same chat_id with different bots = separate message histories)
        same_bot = (
            cp_chat_id == primary_chat_id
            and cp_cfg
            and primary_cfg
            and cp_cfg.get("token") == primary_cfg.get("token")
        )
        if cp_chat_id and not same_bot:
            if is_outbound:
                mirror_emoji = "📥"
                mirror_header = f"From {from_agent}: {subject}"
            else:
                mirror_emoji = "📨"
                mirror_header = f"To {agent_id}: {subject}"
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
