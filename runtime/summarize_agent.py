#!/usr/bin/env python3
"""
Summarize an agent's activity into Task Memory.
Usage: python summarize_agent.py <agent_id>
Called by cron every 4h and by agents on task completion.
Skips LLM call entirely if no new BB or log entries since last summary.
"""
import sys, json, pathlib, datetime, requests

GATEWAY_PORTS = {
    "songbird":     8648,
    "proteus":      8645,
    "stormtrooper": 8646,
    "hermes":       8641,
    "mnemosyne":    8642,
}

BB_ROOT = pathlib.Path("/home/andjesse/.maestro/blackboards")
LOG_ROOT = pathlib.Path("/home/andjesse/.maestro/logs")
MEMORY_ROOT = pathlib.Path("/home/andjesse/.maestro/memory")
AUTH = "Bearer maestro-local-dev"


def get_last_generated_at(agent_id: str):
    p = MEMORY_ROOT / f"{agent_id}_task_memory.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text()).get("generated_at")
    except Exception:
        return None


def get_new_bb_entries(agent_id: str, since: str | None) -> list:
    p = BB_ROOT / f"{agent_id}_bb.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, list):
            return []
        if since is None:
            return data
        return [e for e in data if e.get("ts", "") > since]
    except Exception:
        return []


def get_new_log_entries(agent_id: str, since: str | None) -> list:
    p = LOG_ROOT / f"{agent_id}.jsonl"
    if not p.exists():
        return []
    results = []
    try:
        with open(p) as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if since is None or e.get("ts", "") > since:
                        results.append(e)
                except Exception:
                    continue
    except Exception:
        return []
    return results[-200:]  # cap at 200 entries


def summarize(agent_id: str):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    last_generated = get_last_generated_at(agent_id)

    new_bb = get_new_bb_entries(agent_id, since=last_generated)
    new_logs = get_new_log_entries(agent_id, since=last_generated)

    MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = MEMORY_ROOT / f"{agent_id}_task_memory.json"

    # Load existing memory file if present
    existing = {}
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text())
        except Exception:
            pass

    # Skip LLM if nothing new
    if not new_bb and not new_logs:
        existing["stale"] = True
        existing["stale_checked_at"] = now
        out_path.write_text(json.dumps(existing, indent=2))
        print(f"No new activity for {agent_id} — skipped LLM, marked stale")
        return

    prompt = f"""You are {agent_id}. Summarize your recent activity into a Task Memory entry.

New BB entries (plain English, since last summary):
{json.dumps(new_bb, indent=2)}

New work log entries (technical, since last summary):
{json.dumps(new_logs, indent=2)}

Write a JSON object with these exact fields:
- summary: 2-4 sentences in plain English. What were you working on? What was accomplished?
- completed_items: array of strings, one per completed task
- in_progress_items: array of strings, one per in-progress task
- blocked_items: array of strings, one per blocked task

Return ONLY valid JSON. No markdown fences, no explanation."""

    port = GATEWAY_PORTS.get(agent_id, 8645)
    try:
        resp = requests.post(
            f"http://localhost:{port}/v1/chat/completions",
            headers={"Authorization": AUTH, "Content-Type": "application/json"},
            json={
                "model": "hermes-agent",
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=120,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        # Strip markdown fences if model ignores instructions
        if content.startswith("```"):
            parts = content.split("```")
            content = parts[1] if len(parts) > 1 else content
            if content.startswith("json"):
                content = content[4:]
        summary_data = json.loads(content.strip())
    except Exception as e:
        print(f"Summarization failed for {agent_id}: {e}", file=sys.stderr)
        summary_data = {
            "summary": f"Summarization failed at {now}: {e}",
            "completed_items": [],
            "in_progress_items": [],
            "blocked_items": [],
        }

    output = {
        **existing,
        "generated_at": now,
        "agent_id": agent_id,
        "stale": False,
        "source_window": f"{last_generated or 'beginning'} to {now}",
        **summary_data,
    }
    out_path.write_text(json.dumps(output, indent=2))
    print(f"Task Memory written for {agent_id}: {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: summarize_agent.py <agent_id>")
        sys.exit(1)
    summarize(sys.argv[1])
