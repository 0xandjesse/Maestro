#!/usr/bin/env python3
"""
maestro-broadcast.py — Push-based P2N broadcast for the Maestro swarm.

Reads ~/.maestro/registry.json and fires individual messages to every agent
(excluding the sender) via the local gateway bridge. Reports per-agent delivery
status.

Usage:
    python3 maestro-broadcast.py --from songbird --message "All agents report in"
    python3 maestro-broadcast.py --from songbird --file /path/to/message.md
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

REGISTRY_PATH = Path.home() / ".maestro" / "registry.json"
BRIDGE_URL = "http://127.0.0.1:8653/maestro/notify"


def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        print(f"ERROR: Registry not found at {REGISTRY_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(REGISTRY_PATH, "r") as f:
        return json.load(f)


def resolve_name(registry: dict, agent_id: str) -> str:
    for uid, entry in registry.items():
        if isinstance(entry, dict) and entry.get("agentId") == agent_id:
            return entry.get("agentId", agent_id)
    return agent_id


def send_to_agent(sender: str, target: str, content: str) -> dict:
    payload = {
        "from": sender,
        "agent_id": target,
        "to": target,
        "content": content,
        "msg_type": "direct",
        "visibility": "heartbeat",
    }
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        BRIDGE_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=10) as resp:
            return {"ok": True, "status": resp.status, "body": resp.read().decode()}
    except HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
    except URLError as e:
        return {"ok": False, "error": f"URL error: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Broadcast a message to all Maestro agents")
    parser.add_argument("--from", "-f", dest="sender", required=True, help="Sender agent ID")
    parser.add_argument("--message", "-m", help="Message text (inline)")
    parser.add_argument("--file", help="Path to a file containing the message")
    parser.add_argument("--exclude", "-x", nargs="+", default=[], help="Additional agent IDs to exclude")
    args = parser.parse_args()

    if args.file:
        content = Path(args.file).read_text()
    elif args.message:
        content = args.message
    else:
        print("ERROR: Provide --message or --file", file=sys.stderr)
        sys.exit(1)

    registry = load_registry()
    sender_id = args.sender.lower()
    excluded = {sender_id} | {x.lower() for x in args.exclude}

    targets = []
    for uid, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        aid = entry.get("agentId", "").lower()
        if aid and aid not in excluded:
            targets.append(aid)

    if not targets:
        print("WARNING: No targets found after exclusions", file=sys.stderr)
        sys.exit(0)

    print(f"Broadcasting from '{args.sender}' to {len(targets)} agent(s): {', '.join(targets)}")
    print("-" * 50)

    ok_count = 0
    fail_count = 0
    for target in targets:
        result = send_to_agent(args.sender, target, content)
        status = "✓ OK" if result["ok"] else f"✗ FAIL"
        detail = result.get("body", result.get("error", ""))
        print(f"  {status}  {target:15s}  {detail[:60]}")
        if result["ok"]:
            ok_count += 1
        else:
            fail_count += 1

    print("-" * 50)
    print(f"Done: {ok_count} delivered, {fail_count} failed")
    sys.exit(0 if fail_count == 0 else 1)


if __name__ == "__main__":
    main()
