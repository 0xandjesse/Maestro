#!/usr/bin/env node
/**
 * maestro session — list, validate, or recover sessions
 */
import os from "os";
import path from "path";
import fs from "fs";

const SESSIONS_DIR = path.join(os.homedir(), ".hermes", "sessions");
const SESSIONS_JSON = path.join(SESSIONS_DIR, "sessions.json");

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
    return recoverSession(sid);
  }
  if (sub === "validate") {
    return validateSessions();
  }
  console.log("Usage: maestro session [list | validate | recover <id>]");
}

function loadSessionsJson() {
  if (!fs.existsSync(SESSIONS_JSON)) return {};
  try {
    return JSON.parse(fs.readFileSync(SESSIONS_JSON, "utf8"));
  } catch (e) {
    console.error("Failed to parse sessions.json:", e.message);
    return {};
  }
}

function saveSessionsJson(data) {
  try {
    const tmp = SESSIONS_JSON + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify(data, null, 2));
    fs.renameSync(tmp, SESSIONS_JSON);
  } catch (e) {
    console.error("Failed to save sessions.json:", e.message);
    process.exit(1);
  }
}

function listSessions() {
  const data = loadSessionsJson();
  const entries = Object.values(data);
  if (!entries.length) {
    console.log("No sessions found.");
    return;
  }
  console.log(
    `${"Session ID".padEnd(30)} ${"Platform".padEnd(12)} ${"Status".padEnd(14)} ${"Tokens".padEnd(8)} Chat`
  );
  console.log("-".repeat(90));
  for (const e of entries) {
    const status = e.orphan_status || (e.resume_pending ? "resume_pending" : e.suspended ? "suspended" : "active");
    console.log(
      `${(e.session_id || "").substring(0, 28).padEnd(30)} ${(e.platform || "").padEnd(12)} ${status.padEnd(14)} ${(e.total_tokens || 0).toString().padEnd(8)} ${e.display_name || e.session_key || ""}`
    );
  }
  console.log(`\nTotal: ${entries.length} session(s)`);
}

function validateSessions() {
  const data = loadSessionsJson();
  let changed = false;
  const nowIso = new Date().toISOString();
  const registryPath = path.join(os.homedir(), ".maestro", "registry.json");
  let registry = { agents: {} };
  try {
    if (fs.existsSync(registryPath)) {
      registry = JSON.parse(fs.readFileSync(registryPath, "utf8"));
    }
  } catch {
    // ignore
  }

  let orphaned = 0;
  const agents = registry.agents || {};

  for (const [key, entry] of Object.entries(data)) {
    let status = "";
    let reason = "";

    // Check if any agent in registry is alive
    let aliveAgent = null;
    for (const [, info] of Object.entries(agents)) {
      if (info.status && info.status !== "orphaned") {
        try {
          process.kill(info.pid, 0);
          aliveAgent = info;
          break;
        } catch {
          // dead
        }
      }
    }

    if (!aliveAgent) {
      status = "orphaned";
      reason = "no alive agent in registry";
    } else {
      // alive
      status = "valid";
      reason = "";
    }

    entry.orphan_status = status;
    entry.last_validated_at = nowIso;
    entry.last_validation_reason = reason || null;
    if (status === "orphaned") {
      entry.validation_failures = (entry.validation_failures || 0) + 1;
      orphaned++;
    }
    changed = true;
  }

  if (changed) {
    saveSessionsJson(data);
  }

  if (orphaned) {
    console.log(`Validated ${Object.keys(data).length} session(s). ${orphaned} orphaned.`);
  } else {
    console.log(`Validated ${Object.keys(data).length} session(s). All valid.`);
  }
}

function recoverSession(sid) {
  const data = loadSessionsJson();
  let foundKey = null;
  for (const [key, entry] of Object.entries(data)) {
    if (entry.session_id === sid) {
      foundKey = key;
      break;
    }
  }
  if (!foundKey) {
    console.error(`Session '${sid}' not found in sessions.json.`);
    process.exit(1);
  }
  const entry = data[foundKey];
  if (entry.orphan_status === "orphaned") {
    console.error(
      `Session '${sid}' is orphaned (${entry.last_validation_reason || "unknown reason"}).`
    );
    console.error("Cannot recover orphaned sessions. Gateway restart required.");
    process.exit(1);
  }

  // Mark resume_pending so gateway reconnects on next message
  entry.resume_pending = true;
  entry.resume_reason = "manual_recover";
  entry.last_resume_marked_at = new Date().toISOString();

  saveSessionsJson(data);
  console.log(`Session '${sid}' marked for recovery. Next message will auto-resume.`);
  console.log(`Session key: ${foundKey}`);
}

main();
