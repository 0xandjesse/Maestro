#!/usr/bin/env node
/**
 * Maestro CLI — Node.js entry point
 * Subcommands: init, status, session, secrets
 */

import { spawn } from "child_process";
import { fileURLToPath } from "url";
import path from "path";
import fs from "fs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const COMMANDS = {
  init: { script: "init.js", description: "Set up your agent (wizard)" },
  status: { script: "status.js", description: "Show runtime registry and agent health" },
  session: { script: "session.js", description: "List / validate / recover sessions (list | validate | recover <id>)" },
  secrets: { script: "secrets.js", description: "Backup / restore / list secrets" },
};

function printHelp() {
  console.log(`Maestro CLI — one-line install for autonomous AI agents\n`);
  console.log(`Usage: maestro <command> [args]\n`);
  console.log("Commands:");
  for (const [name, meta] of Object.entries(COMMANDS)) {
    console.log(`  ${name.padEnd(10)} ${meta.description}`);
  }
  console.log("\nRun 'maestro init' to get started.");
}

function main() {
  const args = process.argv.slice(2);
  const cmd = args[0];

  if (!cmd || cmd === "--help" || cmd === "-h") {
    printHelp();
    process.exit(0);
  }

  if (!COMMANDS[cmd]) {
    console.error(`Unknown command: ${cmd}`);
    printHelp();
    process.exit(1);
  }

  const scriptPath = path.join(__dirname, COMMANDS[cmd].script);
  if (!fs.existsSync(scriptPath)) {
    console.error(`Command script not found: ${scriptPath}`);
    process.exit(1);
  }

  const child = spawn(process.execPath, [scriptPath, ...args.slice(1)], {
    stdio: "inherit",
    cwd: process.cwd(),
  });

  child.on("exit", (code) => process.exit(code ?? 0));
  child.on("error", (err) => {
    console.error(`Failed to run ${cmd}:`, err.message);
    process.exit(1);
  });
}

main();
