#!/usr/bin/env python3
"""
EOD Report Generator — runs at 3:30am, fires from Proteus to Songbird.

Collects:
  - Proteus BB (last 4h activity)
  - Stormtrooper BB (last 4h activity)
  - Active and recently completed checklists
  - Proteus work log (last 24h)
  - Any blocked items

Sends structured report to Songbird gateway via Maestro.
Usage: python3 eod_report.py
"""

import json
import pathlib
import datetime
import urllib.request
import urllib.error
import sys

BLACKBOARDS_ROOT = pathlib.Path("/home/andjesse/.maestro/blackboards")
CHECKLISTS_ROOT  = pathlib.Path("/home/andjesse/.maestro/checklists")
LOGS_ROOT        = pathlib.Path("/home/andjesse/.maestro/logs")

GATEWAY_PORTS = {
    "songbird":     8649,
    "hermes":       8641,
    "mnemosyne":    8642,
    "proteus":      8645,
    "stormtrooper": 8646,
}
API_KEY = "maestro-local-dev"

def _now():
    return datetime.datetime.now(datetime.timezone.utc)

def _read_bb(agent_id: str) -> list:
    path = BLACKBOARDS_ROOT / f"{agent_id}_bb.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return list(data.values()) if data else []
    except Exception:
        return []
    return []

def _read_work_log(agent_id: str, hours: int = 24) -> list:
    """Read agent work log entries from the last N hours."""
    cutoff = _now() - datetime.timedelta(hours=hours)
    entries = []
    log_dir = LOGS_ROOT / agent_id
    if not log_dir.exists():
        return []
    for log_file in sorted(log_dir.glob("*.jsonl"), reverse=True)[:3]:
        try:
            for line in log_file.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts_str = entry.get("ts") or entry.get("timestamp") or ""
                    if ts_str:
                        ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if ts >= cutoff:
                            entries.append(entry)
                except Exception:
                    continue
        except Exception:
            continue
    return entries

def _read_checklists() -> dict:
    """Return active + recently completed checklists."""
    active = []
    recently_done = []
    cutoff = _now() - datetime.timedelta(hours=24)

    if not CHECKLISTS_ROOT.exists():
        return {"active": [], "recently_completed": []}

    for cl_file in CHECKLISTS_ROOT.glob("*.json"):
        try:
            cl = json.loads(cl_file.read_text())
        except Exception:
            continue

        status = cl.get("status", "active")
        if status == "active":
            total = len(cl.get("items", []))
            done = sum(1 for i in cl.get("items", []) if i.get("status") == "done")
            blocked = sum(1 for i in cl.get("items", []) if i.get("status") == "blocked")
            active.append({
                "id": cl["id"],
                "title": cl.get("title", ""),
                "created_by": cl.get("created_by", ""),
                "assigned_to": cl.get("assigned_to", ""),
                "progress": f"{done}/{total} done" + (f", {blocked} blocked" if blocked else ""),
                "last_ping_at": cl.get("last_ping_at"),
                "blocked_items": [
                    {"id": i["id"], "description": i["description"], "summary": i.get("summary", "")}
                    for i in cl.get("items", []) if i.get("status") == "blocked"
                ],
                "pending_items": [
                    {"id": i["id"], "description": i["description"]}
                    for i in cl.get("items", []) if i.get("status") == "pending"
                ],
            })
        elif status == "completed":
            completed_at = cl.get("completed_at", "")
            if completed_at:
                try:
                    ts = datetime.datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                    if ts >= cutoff:
                        recently_done.append({
                            "id": cl["id"],
                            "title": cl.get("title", ""),
                            "assigned_to": cl.get("assigned_to", ""),
                            "completed_at": completed_at,
                        })
                except Exception:
                    pass

    return {"active": active, "recently_completed": recently_done}

def _bb_summary(entries: list, agent_id: str) -> str:
    if not entries:
        return f"  {agent_id}: no BB entries in last 4h"
    lines = [f"  {agent_id} ({len(entries)} entries):"]
    # Show last 8 entries
    for e in entries[-8:]:
        ts = e.get("ts", "")[-8:] if e.get("ts") else "?"  # just time portion
        status = e.get("status", "?")
        desc = e.get("description", "")[:80]
        duration = f" ({e['duration_min']}min)" if e.get("duration_min") else ""
        lines.append(f"    [{status}]{duration} {desc}")
    return "\n".join(lines)

def _cl_summary(cl_data: dict) -> str:
    lines = []
    if cl_data["active"]:
        lines.append(f"ACTIVE CHECKLISTS ({len(cl_data['active'])}):")
        for cl in cl_data["active"]:
            lines.append(f"  {cl['id']}  \"{cl['title']}\"")
            lines.append(f"    {cl['created_by']} → {cl['assigned_to']} | {cl['progress']}")
            if cl["blocked_items"]:
                for b in cl["blocked_items"]:
                    lines.append(f"    ⚠ BLOCKED {b['id']}: {b['description'][:60]}")
                    if b["summary"]:
                        lines.append(f"      reason: {b['summary'][:80]}")
            if cl["pending_items"]:
                next_item = cl["pending_items"][0]
                desc = next_item['description']
                if isinstance(desc, dict):
                    desc = desc.get('description', str(desc))
                lines.append(f"    → next: {next_item['id']}: {str(desc)[:60]}")
    else:
        lines.append("ACTIVE CHECKLISTS: none")

    if cl_data["recently_completed"]:
        lines.append(f"\nCOMPLETED TODAY ({len(cl_data['recently_completed'])}):")
        for cl in cl_data["recently_completed"]:
            lines.append(f"  {cl['id']}  \"{cl['title']}\" (assigned to {cl['assigned_to']})")

    return "\n".join(lines)

def build_report() -> str:
    now = _now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M UTC")

    proteus_bb   = _read_bb("proteus")
    storm_bb     = _read_bb("stormtrooper")
    cl_data      = _read_checklists()

    # Count any blockers
    all_blockers = []
    for cl in cl_data["active"]:
        for b in cl["blocked_items"]:
            all_blockers.append(f"{cl['id']} item {b['id']}: {b['description'][:60]}")
    for e in proteus_bb + storm_bb:
        if isinstance(e, dict) and e.get("status") == "blocked":
            all_blockers.append(f"BB: {e.get('description','')[:80]}")

    report_lines = [
        f"# EOD Report — {date_str} ({time_str})",
        f"Prepared by: Proteus",
        f"",
        f"## BLACKBOARD ACTIVITY (last 4h)",
        _bb_summary(proteus_bb, "proteus"),
        _bb_summary(storm_bb, "stormtrooper"),
        f"",
        f"## CHECKLISTS",
        _cl_summary(cl_data),
        f"",
    ]

    if all_blockers:
        report_lines += [
            f"## ⚠ BLOCKERS REQUIRING ATTENTION",
        ]
        for b in all_blockers:
            report_lines.append(f"  - {b}")
        report_lines.append("")

    report_lines += [
        f"## NEEDS ATTENTION TOMORROW",
    ]

    # Active CLs with pending work
    needs_attention = []
    for cl in cl_data["active"]:
        if cl["pending_items"]:
            next_item = cl["pending_items"][0]
            next_desc = next_item["description"]
            if isinstance(next_desc, dict):
                next_desc = next_desc.get("description", str(next_desc))
            needs_attention.append(
                f"  - {cl['id']} \"{cl['title']}\": {len(cl['pending_items'])} items pending, "
                f"next → {next_item['id']}: {str(next_desc)[:50]}"
            )
    if needs_attention:
        report_lines += needs_attention
    else:
        report_lines.append("  - No outstanding checklist items")

    report_lines += [
        "",
        f"---",
        f"Report generated: {now.isoformat()}",
    ]

    return "\n".join(report_lines)

def send_to_songbird(report: str):
    port = GATEWAY_PORTS["songbird"]
    payload = {
        "model": "hermes-agent",
        "messages": [{
            "role": "user",
            "content": (
                "PROTEUS EOD REPORT — read and acknowledge receipt. "
                "You do not need to act on this now — this is for your memory update at 3:45am.\n\n"
                + report
            ),
        }],
        "stream": False,
        "conversation_id": "proteus-eod-report",
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://localhost:{port}/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(f"Delivered to Songbird gateway: {resp.status}")
    except urllib.error.URLError as e:
        print(f"Failed to deliver to Songbird: {e}", file=sys.stderr)
        # Still print the report so cron output is useful
        print("\n--- REPORT (delivery failed, printing for log) ---")
        print(report)

if __name__ == "__main__":
    report = build_report()
    print(report)
    send_to_songbird(report)
