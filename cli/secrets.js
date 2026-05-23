#!/usr/bin/env node
/**
 * maestro secrets — backup / restore / list
 */
import os from "os";
import path from "path";
import fs from "fs";

const MAESTRO = path.join(os.homedir(), ".maestro");
const SECRETS = path.join(MAESTRO, "secrets.env");
const BACKUPS = path.join(MAESTRO, "backups");

function ensureBackups() {
  if (!fs.existsSync(BACKUPS)) fs.mkdirSync(BACKUPS, { recursive: true });
}

function ensureSecretsMode() {
  try {
    fs.chmodSync(SECRETS, 0o600);
  } catch {}
}

function listSecrets() {
  if (!fs.existsSync(SECRETS)) {
    console.log("No secrets.env found.");
    return;
  }
  const lines = fs.readFileSync(SECRETS, "utf8").split("\n").filter(Boolean);
  for (const line of lines) {
    if (line.startsWith("#")) {
      console.log(line);
      continue;
    }
    const [key] = line.split("=");
    if (key) console.log(`${key}=***`);
  }
}

function backupSecrets() {
  ensureBackups();
  if (!fs.existsSync(SECRETS)) {
    console.error("No secrets.env to backup.");
    process.exit(1);
  }
  ensureSecretsMode();
  const stamp = new Date().toISOString().replace(/[:T]/g, "-").split(".")[0];
  const dest = path.join(BACKUPS, `secrets-${stamp}.env`);
  fs.copyFileSync(SECRETS, dest);
  fs.chmodSync(dest, 0o600);
  console.log(`Backup created: ${dest}`);
}

function restoreSecrets(dateArg) {
  const files = fs.readdirSync(BACKUPS).filter((f) => f.startsWith("secrets-") && f.endsWith(".env")).sort();
  if (!files.length) {
    console.error("No backups found.");
    process.exit(1);
  }
  let target;
  if (dateArg) {
    target = files.find((f) => f.includes(dateArg));
    if (!target) {
      console.error(`No backup matching '${dateArg}' found.`);
      process.exit(1);
    }
  } else {
    target = files[files.length - 1];
  }
  const src = path.join(BACKUPS, target);
  if (!fs.existsSync(SECRETS)) {
    fs.mkdirSync(MAESTRO, { recursive: true });
  }
  fs.copyFileSync(src, SECRETS);
  fs.chmodSync(SECRETS, 0o600);
  console.log(`Restored secrets from ${src}`);
}

function main() {
  const args = process.argv.slice(2);
  const sub = args[0] || "list";
  if (sub === "list") return listSecrets();
  if (sub === "backup") return backupSecrets();
  if (sub === "restore") return restoreSecrets(args[1]);
  console.log("Usage: maestro secrets [list | backup | restore <date>]");
}

main();
