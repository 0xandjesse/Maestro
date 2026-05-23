#!/usr/bin/env python3
"""Quick CLI for Maestro notification toggling and work log queries.

Usage:
    python maestro_status.py off          # silence Maestro notifications
    python maestro_status.py on           # resume Maestro notifications
    python maestro_status.py query [AGENT] [LIMIT]   # read work log

Or send commands to any transport endpoint:
    python maestro_status.py toggle proteus true
    python maestro_status.py query hermes 5
"""
import sys, json
from urllib.request import urlopen, Request

TRANSPORTS = {
    "proteus": 3846,
    "songbird": 3842,
    "lexicon": 3843,
    "hermes": 3844,
    "mnemosyne": 3845,
}

def _post(port, path, data):
    body = json.dumps(data).encode()
    req = Request(f"http://127.0.0.1:{port}{path}", data=body, headers={"Content-Type":"application/json"})
    return json.loads(urlopen(req).read())

def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: maestro_status.py [on|off|query] [agent] [limit]")
        return

    cmd = args[0].lower()
    if cmd in ("on", "off"):
        enabled = cmd == "on"
        target = args[1] if len(args) > 1 else "proteus"
        port = TRANSPORTS.get(target)
        if not port:
            print(f"Unknown agent: {target}")
            return
        result = _post(port, "/maestro/notifications/toggle", {"enabled": enabled})
        print(json.dumps(result, indent=2))

    elif cmd == "query":
        target = args[1] if len(args) > 1 else "proteus"
        limit = int(args[2]) if len(args) > 2 else 10
        port = TRANSPORTS.get(target)
        if not port:
            print(f"Unknown agent: {target}")
            return
        result = _post(port, "/maestro/worklog/query", {"agent_id": target, "limit": limit})
        for e in result.get("entries", []):
            print(f"[{e.get('timestamp_iso','?')}] {e.get('sender','?')}: {e.get('content','')[:120]}")

    else:
        print(f"Unknown command: {cmd}")

if __name__ == "__main__":
    main()
