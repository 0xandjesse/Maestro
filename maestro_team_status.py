#!/usr/bin/env python3
"""
Team Status Query for Maestro Agent Mesh
Queries all agents' worklogs and produces a formatted report.
"""

import json, urllib.request, sys

AGENTS = {
    "songbird": 3842,
    "lexicon": 3843,
    "hermes": 3844,
    "mnemosyne": 3845,
    "proteus": 3846,
}

def query_worklog(agent_id, port, limit=5):
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/maestro/worklog/query",
            data=json.dumps({"limit": limit, "agent_id": agent_id}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}

def query_health(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}

def fmt_entry(e):
    ts = e.get("timestamp", "?")
    src = e.get("sender", {}).get("agentId", e.get("sender", "?")) if isinstance(e.get("sender"), dict) else e.get("sender", "?")
    typ = e.get("type", e.get("msg_type", "?"))
    content = e.get("content", "")
    if isinstance(content, dict):
        content = json.dumps(content)
    if len(content) > 120:
        content = content[:117] + "..."
    return f"  [{ts}] {typ.upper()} from {src}: {content}"

def main(limit=5, include_health=False):
    lines = ["📋 Maestro Team Status", "═" * 30, ""]
    for agent_id, port in AGENTS.items():
        status = query_health(port) if include_health else {"ok": True}
        if not status.get("ok"):
            lines.append(f"🔴 {agent_id.upper()} — DOWN ({status.get('error', 'N/A')})")
            continue
        lines.append(f"🟢 {agent_id.upper()}")
        wl = query_worklog(agent_id, port, limit)
        if not wl.get("ok"):
            lines.append(f"       worklog error: {wl.get('error', 'N/A')}")
        elif not wl.get("entries"):
            lines.append("       (no recent activity)")
        else:
            for e in wl["entries"]:
                lines.append(fmt_entry(e))
        lines.append("")
    lines.append("═" * 30)
    return "\n".join(lines)

if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    include_health = "--health" in sys.argv
    print(main(limit=limit, include_health=include_health))
