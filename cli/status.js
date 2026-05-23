#!/usr/bin/env node
/**
 * maestro status — read runtime registry and print agent health table
 *
 * Reads ~/.maestro/registry.json and prints a table with:
 *   Agent | PID | Port | Status | Uptime
 *
 * Supports two registry formats:
 *   1. { agents: { <id>: { pid, port, status, started } } }
 *   2. [ { agentId, webhookEndpoint, ... } ]  (flat array)
 */
import os from "os";
import path from "path";
import fs from "fs";

const REGISTRY = path.join(os.homedir(), ".maestro", "registry.json");

function main() {
  if (!fs.existsSync(REGISTRY)) {
    console.log("No registry found. Run 'maestro init' first.");
    process.exit(0);
  }

  let data;
  try {
    data = JSON.parse(fs.readFileSync(REGISTRY, "utf8"));
  } catch (e) {
    console.error("Corrupt registry:", e.message);
    process.exit(1);
  }

  // Normalize to array of agent records
  let agents;
  if (Array.isArray(data)) {
    // Format 2: flat array of objects
    agents = data;
  } else if (data.agents && typeof data.agents === "object") {
    // Format 1: { agents: { id: {...}, ... } }
    agents = Object.entries(data.agents).map(([id, v]) => ({ agentId: id, ...v }));
  } else {
    console.log("No registered agents.");
    process.exit(0);
  }

  if (!agents.length) {
    console.log("No registered agents.");
    process.exit(0);
  }

  const now = Date.now();

  // Print header
  console.log("Maestro Runtime Status\n");
  console.log(
    `${"Agent".padEnd(16)} ${"PID".padEnd(8)} ${"Alive".padEnd(6)} ${"Port".padEnd(6)} ${"Status".padEnd(10)} Uptime`
  );
  console.log("-".repeat(72));

  for (const a of agents) {
    const id = a.agentId || "?";
    const pid = a.pid || "N/A";
    const alive = a.pid ? isAlive(a.pid) : false;
    const port = extractPort(a) || "N/A";
    const status = a.status || "registered";
    const uptime = formatUptime(a.registeredAt || a.started, now);
    console.log(
      `${id.padEnd(16)} ${String(pid).padEnd(8)} ${(alive ? "yes" : "no").padEnd(6)} ${String(port).padEnd(6)} ${status.padEnd(10)} ${uptime}`
    );
  }
}

/** Extract port from webhookEndpoint or direct port field */
function extractPort(agent) {
  if (agent.port) return agent.port;
  if (agent.webhookEndpoint) {
    const m = agent.webhookEndpoint.match(/:(\d+)\//);
    if (m) return m[1];
  }
  return null;
}

/** Check if a PID is alive (signal 0 = existence check) */
function isAlive(pid) {
  try {
    process.kill(Number(pid), 0);
    return true;
  } catch {
    return false;
  }
}

/** Format milliseconds since epoch to human-readable uptime */
function formatUptime(startMs, nowMs) {
  if (!startMs) return "N/A";
  const diffMs = nowMs - startMs;
  if (diffMs < 0) return "just now";
  const secs = Math.floor(diffMs / 1000);
  const mins = Math.floor(secs / 60);
  const hrs = Math.floor(mins / 60);
  if (hrs > 0) return `${hrs}h ${mins % 60}m`;
  if (mins > 0) return `${mins}m ${secs % 60}s`;
  return `${secs}s`;
}

main();