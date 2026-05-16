"""
Structured JSONL logger for Maestro transport.
Appends one line per message to ~/.maestro/logs/{agent_id}.jsonl

Schema per line:
  {
    "ts":         "2026-05-16T01:23:45.678Z",   # ISO 8601 UTC
    "agent_id":   "proteus",                     # agent writing the log
    "action":     "send" | "receive",
    "params":     { ... },                       # message payload (truncated if large)
    "result":     "...",                         # response text (truncated if large)
    "session_id": "abc123"                       # optional, may be None
  }

Usage (from maestro_transport.py):
    from log_writer import log_message

    # On send:
    log_message(agent_id, "send", params=message_dict, result=response_str, session_id=sid)

    # On receive:
    log_message(agent_id, "receive", params=message_dict, result=None, session_id=sid)
"""
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

LOG_ROOT = Path(os.getenv("MAESTRO_LOG_ROOT", os.path.expanduser("~/.maestro/logs")))
_MAX_FIELD_CHARS = 4000   # truncate large payloads so logs stay readable
_lock = threading.Lock()


def _truncate(value, max_chars: int = _MAX_FIELD_CHARS):
    """Truncate strings; summarise large dicts/lists."""
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars] + f"... [truncated {len(value) - max_chars} chars]"
    if isinstance(value, (dict, list)):
        encoded = json.dumps(value)
        if len(encoded) > max_chars:
            return json.loads(encoded[:max_chars].rsplit(",", 1)[0] + "}") if isinstance(value, dict) else \
                   encoded[:max_chars] + "... [truncated]"
    return value


def log_message(
    agent_id: str,
    action: str,
    params: dict = None,
    result: str = None,
    session_id: str = None,
) -> None:
    """
    Append one structured log entry for a Maestro message.

    Parameters
    ----------
    agent_id   : The agent this transport instance serves (e.g. "proteus")
    action     : "send" or "receive"
    params     : The full message dict being sent/received
    result     : Response text returned by the gateway (None for receive events)
    session_id : Optional session identifier
    """
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = LOG_ROOT / f"{agent_id}.jsonl"

    entry = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "agent_id": agent_id,
        "action": action,
        "params": _truncate(params or {}),
        "result": _truncate(result) if result is not None else None,
        "session_id": session_id,
    }

    line = json.dumps(entry, ensure_ascii=False)
    with _lock:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
