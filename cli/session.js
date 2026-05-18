#!/usr/bin/env node
/**
 * maestro session — list or recover sessions
 */
import os from "os";
import path from "path";
import fs from "fs";

const SESSIONS_DIR = path.join(os.homedir(), ".hermes", "sessions");

function main() {
  const args = process.argv.slice(2);
  const sub = args[0] || "list";
  if (sub === "list") {
    return listSessions();
  }
  if (sub === "recover") {
    const sid = args[1];
    if (!sid) {
      console.error("Usage: maestro session recover <session-id>");
      process.exit(1);
    }
    console.log(`Recovery request for ${sid} — requires gateway restart to reconnect.`);
    return;
  }
  console.log("Usage: maestro session [list | recover <id>]");
}

function listSessions() {
  if (!fs.existsSync(SESSIONS_DIR)) {
    console.log("No sessions directory found.");
    return;
  }
  const files = fs.readdirSync(SESSIONS_DIR).filter((f) => f.endsWith(".json"));
  if (!files.length) {
    console.log("No session files.");
    return;
  }
  console.log(`${"Session".padEnd(40)} ${"Modified".padEnd(20)} Size`);
  console.log("-".repeat(80));
  for (const f of files) {
    const p = path.join(SESSIONS_DIR, f);
    const stat = fs.statSync(p);
    console.log(`${f.padEnd(40)} ${new Date(stat.mtime).toISOString().padEnd(20)} ${stat.size}`);
  }
}

main();
