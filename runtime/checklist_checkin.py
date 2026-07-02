#!/usr/bin/env python3
"""Check-in cron for Checklist owners.

Scans active CLs, pings assignee if no completion ping received within checkin_interval_min.
Usage: python checklist_checkin.py <owner_agent_id>
"""
import sys
import json
import pathlib
import datetime
import requests

CL_ROOT = pathlib.Path("/home/andjesse/.maestro/checklists")
GATEWAY_PORTS = {
    "songbird": 8642,
    "proteus": 8645,
    "stormtrooper": 8646,
    "hermes": 8641,
    "lexicon": 8643,
    "mnemosyne": 8647,
}
AUTH = "Bearer maestro-local-dev"


def _get_next_item_desc(cl: dict) -> str:
    for item in cl.get("items", []):
        if item.get("status") not in ("done", "blocked"):
            return f"{item['id']}: {item['description']}"
    return "all items complete or blocked"


def checkin(owner_agent_id: str):
    now = datetime.datetime.now(datetime.timezone.utc)
    for cl_file in CL_ROOT.glob("*.json"):
        try:
            cl = json.loads(cl_file.read_text())
        except Exception:
            continue
        if cl.get("created_by") != owner_agent_id:
            continue
        if cl.get("status") != "active":
            continue

        interval_min = cl.get("checkin_interval_min", 30)
        last_ping = cl.get("last_ping_at")
        assignee = cl.get("assigned_to")

        if last_ping:
            last_ping_dt = datetime.datetime.fromisoformat(last_ping.replace("Z", "+00:00"))
            elapsed_min = (now - last_ping_dt).total_seconds() / 60
            if elapsed_min < interval_min:
                continue

        # No ping within interval — check their BB
        bb_path = pathlib.Path(f"/home/andjesse/.maestro/blackboards/{assignee}_bb.json")
        bb_stale = True
        if bb_path.exists():
            try:
                entries = json.loads(bb_path.read_text())
                if isinstance(entries, list) and entries:
                    latest_ts = entries[0].get("ts", "")
                    latest_dt = datetime.datetime.fromisoformat(latest_ts.replace("Z", "+00:00"))
                    if (now - latest_dt).total_seconds() / 60 < interval_min:
                        bb_stale = False
            except Exception:
                pass

        if bb_stale:
            port = GATEWAY_PORTS.get(assignee, 8645)
            msg = (f"Check-in from {owner_agent_id}: Checklist {cl['id']} — "
                   f"no update received in {interval_min} minutes. "
                   f"Please send a status update or completion ping. "
                   f"Next item: {_get_next_item_desc(cl)}")
            try:
                requests.post(
                    f"http://localhost:{port}/v1/chat/completions",
                    headers={"Authorization": AUTH, "Content-Type": "application/json"},
                    json={"model": "hermes-agent",
                          "messages": [{"role": "user", "content": msg}],
                          "stream": False},
                    timeout=30,
                )
                print(f"Check-in ping sent to {assignee} for {cl['id']}")
            except Exception as e:
                print(f"Failed to ping {assignee}: {e}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: checklist_checkin.py <owner_agent_id>")
        sys.exit(1)
    checkin(sys.argv[1])
