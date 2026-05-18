#!/usr/bin/env node
/**
 * maestro status — read runtime registry and print agent health
 */
import os from "os";
import path from "path";
import fs from "fs";

const REGISTRY = path.join(os.homedir(), ".maestro", "registry.json");

function main() {
  if (!fs.existsSync(REGISTRY)) {
    console.log("No registry found. No agents running?");
    process.exit(0);
  }
  let data;
  try {
    data = JSON.parse(fs.readFileSync(REGISTRY, "utf8"));
  } catch (e) {
    console.error("Corrupt registry:", e.message);
    process.exit(1);
  }

  const agents = data.agents || {};
  const keys = Object.keys(agents);
  if (!keys.length) {
    console.log("No registered agents.");
    process.exit(0);
  }

  console.log(`Maestro Runtime Status\nLast heartbeat: ${data.last_heartbeat || "N/A"}\n`);
  console.log(`${"Agent".padEnd(20)} ${"PID".padEnd(8)} ${"Alive".padEnd(6)} ${"Port".padEnd(6)} ${"Status".padEnd(10)} Started`);
  console.log("-".repeat(80));
  for (const aid of keys) {
    const a = agents[aid];
    const alive = a.pid ? tryKill(a.pid) : false;
    console.log(
      `${(aid || "?").padEnd(20)} ${(a.pid || "N/A").padEnd(8)} ${(alive ? "yes" : "no").padEnd(6)} ${(a.port || "N/A").padEnd(6)} ${(a.status || "unknown").padEnd(10)} ${a.started || ""}`,
    );
  }
}

function tryKill(pid) {
  try {
    process.kill(Number(pid), 0);
    return true;
  } catch {
    return false;
  }
}

main();
