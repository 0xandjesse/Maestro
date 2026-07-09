#!/usr/bin/env python3
"""
supervisor.py — Periodic health-check daemon for Maestro agents.

Reads ~/.maestro/registry.json and every 60s sends HTTP GET to
localhost:{port}/health for each registered agent. Marks agents as
"stale" if they fail to respond for 3 consecutive checks.

Runs standalone with --daemon flag (forks to background), or inline
with --once for a single pass.

Usage:
    python supervisor.py --once        # single health-check pass
    python supervisor.py --daemon      # run as background daemon
    python supervisor.py --interval 30 # custom interval in seconds
"""

import argparse
try:
    import daemon as unixdaemon  # python-daemon (optional)
except ImportError:
    unixdaemon = None
import fcntl
import http.client
import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
REGISTRY_PATH = Path.home() / ".maestro" / "registry.json"
LOCK_FILE = Path.home() / ".maestro" / "supervisor.lock"
PID_FILE = Path.home() / ".maestro" / "supervisor.pid"
LOG_FILE = Path.home() / ".maestro" / "supervisor.log"
DEFAULT_INTERVAL = 60  # seconds
STALE_THRESHOLD = 3    # consecutive failures before marking stale
_KILL_WAIT_S = 5       # seconds between SIGTERM and SIGKILL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [supervisor] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("supervisor")


def load_registry():
    """Load agent registry. Returns list of agent dicts."""
    if not REGISTRY_PATH.exists():
        log.warning("No registry found at %s", REGISTRY_PATH)
        return []
    try:
        data = json.loads(REGISTRY_PATH.read_text("utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.error("Corrupt registry: %s", e)
        return []

    # Support both formats: flat array or {agents: {...}}
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "agents" in data:
        return [{"agentId": k, **v} for k, v in data["agents"].items()]
    return []


def extract_port(agent):
    """Extract health-check port from agent record."""
    if agent.get("port"):
        return agent["port"]
    ep = agent.get("webhookEndpoint", "")
    # e.g. http://127.0.0.1:3844/message -> 3844
    import re
    m = re.search(r":(\d+)/", ep)
    if m:
        return int(m.group(1))
    return None


def health_check(agent):
    """Send HTTP GET to agent's /health endpoint. Returns (ok: bool, latency_ms: float)."""
    port = extract_port(agent)
    if not port:
        return False, -1

    aid = agent.get("agentId", "?")
    url = f"http://127.0.0.1:{port}/health"
    try:
        start = time.monotonic()
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            latency = (time.monotonic() - start) * 1000
            if resp.status == 200:
                log.debug("  ✓ %s healthy (%.0fms)", aid, latency)
                return True, latency
            else:
                log.warning("  ✗ %s returned HTTP %d", aid, resp.status)
                return False, latency
    except Exception as e:
        log.debug("  ✗ %s unreachable: %s", aid, e)
        return False, -1


def check_all(agents):
    """Run health-check on all agents. Returns list of result dicts."""
    results = []
    for agent in agents:
        aid = agent.get("agentId", "?")
        ok, latency = health_check(agent)
        results.append({
            "agent": aid,
            "healthy": ok,
            "latency_ms": round(latency, 1) if latency >= 0 else None,
        })
    return results


# ── Stale tracking ─────────────────────────────────────────────────────────────
# Persist failure counts in a simple JSON sidecar.
STALE_FILE = Path.home() / ".maestro" / "supervisor_stale.json"


def load_stale_counts():
    """Load consecutive-failure counts from disk."""
    if STALE_FILE.exists():
        try:
            return json.loads(STALE_FILE.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_stale_counts(counts):
    """Persist consecutive-failure counts."""
    try:
        STALE_FILE.write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def update_stale(results):
    """Update failure counts and detect stale agents. Returns list of newly-stale agent IDs."""
    counts = load_stale_counts()
    newly_stale = []
    for r in results:
        aid = r["agent"]
        if r["healthy"]:
            counts.pop(aid, None)
        else:
            counts[aid] = counts.get(aid, 0) + 1
            if counts[aid] >= STALE_THRESHOLD:
                newly_stale.append(aid)
    save_stale_counts(counts)
    return newly_stale


# ── Registry update ───────────────────────────────────────────────────────────
def mark_stale_in_registry(stale_ids):
    """Update registry.json to mark stale agent statuses."""
    if not stale_ids:
        return
    try:
        data = json.loads(REGISTRY_PATH.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    changed = False
    if isinstance(data, list):
        for agent in data:
            if agent.get("agentId") in stale_ids:
                agent["status"] = "stale"
                changed = True
    elif isinstance(data, dict) and "agents" in data:
        for aid in stale_ids:
            if aid in data["agents"]:
                data["agents"][aid]["status"] = "stale"
                changed = True

    if changed:
        try:
            REGISTRY_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass


# ── Kill authority ───────────────────────────────────────────────────────────
def _kill_agent(pid: int, agent_id: str) -> dict:
    """Send SIGTERM, wait 5s, then SIGKILL. Return outcome dict."""
    alive = False
    try:
        os.kill(pid, 0)
        alive = True
    except (OSError, ProcessLookupError):
        pass

    if not alive:
        return {"agent_id": agent_id, "pid": pid, "action": "none", "reason": "already dead"}

    # SIGTERM
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError) as e:
        return {"agent_id": agent_id, "pid": pid, "action": "none", "reason": f"sigterm failed: {e}"}

    # Verify with a short wait (up to _KILL_WAIT_S)
    waited = 0.0
    while waited < _KILL_WAIT_S:
        time.sleep(0.5)
        waited += 0.5
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            # Process is dead after SIGTERM — success
            return {"agent_id": agent_id, "pid": pid, "action": "sigterm", "reason": "terminated gracefully"}

    # Still alive — escalate to SIGKILL
    try:
        os.kill(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass

    # Final verification
    time.sleep(0.5)
    try:
        os.kill(pid, 0)
        return {"agent_id": agent_id, "pid": pid, "action": "sigkill", "reason": "still alive after sigkill"}
    except (OSError, ProcessLookupError):
        return {"agent_id": agent_id, "pid": pid, "action": "sigkill", "reason": "killed after escalation"}


def _execute_kill(stale_ids):
    """Kill stale agents, log results, audit."""
    if not stale_ids:
        return []
    agents = load_registry()
    results = []
    for aid in stale_ids:
        pid = None
        for ag in agents:
            if ag.get("agentId") == aid:
                pid = ag.get("pid")
                break
        if pid is None or not isinstance(pid, int):
            results.append({"agent_id": aid, "pid": pid, "action": "none", "reason": "no pid in registry"})
            continue
        outcome = _kill_agent(pid, aid)
        results.append(outcome)
        log.warning("supervisor_kill  agent=%s pid=%s action=%s reason=%s",
                    outcome["agent_id"], outcome["pid"], outcome["action"], outcome["reason"])

    # Audit log
    try:
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        from audit_log import write as audit_write, EVENT_SUPERVISOR_KILL
        audit_write(EVENT_SUPERVISOR_KILL, {"agents": results})
    except Exception:
        pass
    return results


# ── Single pass ────────────────────────────────────────────────────────────────
def run_once():
    """Single health-check pass over all registered agents."""
    agents = load_registry()
    if not agents:
        log.info("No agents in registry.")
        return

    log.info("Health-checking %d agent(s)...", len(agents))
    results = check_all(agents)

    healthy = [r for r in results if r["healthy"]]
    unhealthy = [r for r in results if not r["healthy"]]
    log.info("Results: %d healthy, %d unhealthy", len(healthy), len(unhealthy))

    if unhealthy:
        for r in unhealthy:
            log.warning("  ✗ %s (latency: %s)", r["agent"], r["latency_ms"])

    newly_stale = update_stale(results)
    if newly_stale:
        log.warning("Marking stale: %s", ", ".join(newly_stale))
        mark_stale_in_registry(newly_stale)
        _execute_kill(newly_stale)

    # Write audit entry
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from audit_log import write as audit_write
        audit_write("supervisor.check", {
            "healthy_count": len(healthy),
            "unhealthy_count": len(unhealthy),
            "stale": newly_stale,
        })
    except Exception:
        pass  # audit is best-effort


# ── Daemon mode ────────────────────────────────────────────────────────────────
def acquire_lock():
    """Ensure only one supervisor daemon runs at a time. Returns fd or None."""
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(LOCK_FILE), os.O_WRONLY | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except (IOError, OSError):
            os.close(fd)
            return None
    except OSError:
        return None


def release_lock(fd):
    """Release the daemon lock."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def write_pid():
    """Write current PID to PID file."""
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    except OSError:
        pass


def run_daemon(interval):
    """Run health-checks in a loop with the given interval (seconds)."""
    fd = acquire_lock()
    if fd is None:
        log.error("Another supervisor daemon is already running (lock: %s)", LOCK_FILE)
        sys.exit(1)

    write_pid()

    # Set up file logging for daemon mode
    fh = logging.FileHandler(LOG_FILE)
    fh.setFormatter(logging.Formatter("%(asctime)s [supervisor] %(levelname)s: %(message)s"))
    log.addHandler(fh)

    def shutdown(signum, frame):
        log.info("Received signal %s, shutting down.", signum)
        release_lock(fd)
        PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    log.info("Supervisor daemon started (interval=%ds, pid=%d)", interval, os.getpid())
    try:
        while True:
            run_once()
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        release_lock(fd)
        PID_FILE.unlink(missing_ok=True)


# ── CLI ────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Maestro agent health supervisor")
    parser.add_argument("--once", action="store_true", help="Run a single health-check pass")
    parser.add_argument("--daemon", action="store_true", help="Run as background daemon")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"Check interval in seconds (default: {DEFAULT_INTERVAL})")
    args = parser.parse_args()

    if args.once:
        run_once()
    elif args.daemon:
        run_daemon(args.interval)
    else:
        # Default: single pass (same as --once)
        run_once()


if __name__ == "__main__":
    main()