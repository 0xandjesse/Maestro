#!/usr/bin/env node
/**
 * Maestro Init Wizard
 * Self-contained. No external deps beyond Node.js stdlib and Python 3.10+.
 */

import { spawn, execSync } from "child_process";
import { createReadStream, createWriteStream, existsSync, mkdirSync, readFileSync, writeFileSync, renameSync } from "fs";
import { createInterface } from "readline";
import path from "path";
import os from "os";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let RL = null;
const MAESTRO_DIR = path.join(os.homedir(), ".maestro");
const VENV_DIR = path.join(MAESTRO_DIR, "venv");
const CONFIG_PATH = path.join(MAESTRO_DIR, "config.yaml");
const ENV_PATH = path.join(MAESTRO_DIR, ".env");
const TRANSPORT_JSON = path.join(MAESTRO_DIR, "maestro_transport.json");
const REGISTRY_PATH = path.join(MAESTRO_DIR, "registry.json");
const RUNTIME_DIR = path.resolve(path.join(__dirname, "..", "runtime"));
const REQUIREMENTS_TXT = path.join(RUNTIME_DIR, "requirements.txt");

const PROVIDERS = {
  ollama:   { label: "Ollama (local)", defaultModel: "llama3.1", needsKey: false },
  anthropic:{ label: "Anthropic",      defaultModel: "claude-3-sonnet-20240229", needsKey: true },
  openai:   { label: "OpenAI",          defaultModel: "gpt-5", needsKey: true },
};

const PLATFORMS = [
  { id: "telegram",      label: "Telegram",     needsToken: true, tokenPrompt: "Paste your Telegram bot token (from @BotFather): ",     envKey: "TELEGRAM_BOT_TOKEN" },
  { id: "discord",       label: "Discord",      needsToken: true, tokenPrompt: "Paste your Discord bot token: ",                     envKey: "DISCORD_BOT_TOKEN" },
  { id: "slack",         label: "Slack",        needsToken: true, tokenPrompt: "Paste your Slack Bot User OAuth Token: ",              envKey: "SLACK_BOT_TOKEN" },
  { id: "whatsapp",      label: "WhatsApp",     needsToken: false },
  { id: "signal",        label: "Signal",       needsToken: false },
  { id: "matrix",        label: "Matrix",       needsToken: true, tokenPrompt: "Paste your Matrix access token: ",                     envKey: "MATRIX_ACCESS_TOKEN" },
  { id: "mattermost",    label: "Mattermost",   needsToken: true, tokenPrompt: "Paste your Mattermost Personal Access Token: ",        envKey: "MATTERMOST_TOKEN" },
  { id: "email",         label: "Email (SMTP/IMAP)", needsToken: false },
  { id: "sms",           label: "SMS",          needsToken: false },
  { id: "homeassistant", label: "Home Assistant", needsToken: true, tokenPrompt: "Paste your Home Assistant Long-Lived Access Token: ", envKey: "HASS_TOKEN" },
];

/* ── helpers ──────────────────────────────────────────────── */

function banner() {
  console.log(`\n  ╔═══════════════════════════════════════════════╗`);
  console.log(`  ║   Welcome to Maestro                          ║`);
  console.log(`  ║   One-line install for autonomous AI agents   ║`);
  console.log(`  ╚═══════════════════════════════════════════════╝\n`);
}

async function ask(question, defaultVal = "") {
  if (!RL) {
    RL = createInterface({ input: process.stdin, output: process.stdout });
  }
  const display = defaultVal ? `${question} [${defaultVal}]: ` : `${question}: `;
  const answer = await new Promise((resolve) => RL.question(display, resolve));
  const trimmed = answer.trim();
  return trimmed || defaultVal;
}

function closeReadline() {
  if (RL) {
    RL.close();
    RL = null;
  }
}

async function askChoice(question, choices) {
  choices.forEach((c, i) => console.log(`  ${i + 1}. ${c}`));
  const raw = await ask(`\n${question} (1-${choices.length})`);
  const idx = parseInt(raw, 10) - 1;
  if (idx < 0 || idx >= choices.length) {
    console.log("Invalid choice, defaulting to 1.");
    return 0;
  }
  return idx;
}

async function confirm(question) {
  const ans = await ask(`${question} (y/n)`, "y");
  return ans.toLowerCase().startsWith("y");
}

function exec(cmd, opts = {}) {
  return execSync(cmd, { stdio: ["ignore", "inherit", "inherit"], cwd: opts.cwd || MAESTRO_DIR, ...opts });
}

function execQuiet(cmd, opts = {}) {
  try {
    const cwd = opts.cwd ?? (existsSync(MAESTRO_DIR) ? MAESTRO_DIR : process.cwd());
    return execSync(cmd, { encoding: "utf-8", cwd, ...opts });
  } catch (e) {
    return null;
  }
}

/* ── Python sanity ───────────────────────────────────────── */

function checkPython() {
  const out = execQuiet("python3 --version") || execQuiet("python --version");
  if (!out) {
    console.error("Python 3.10+ is required but not found.");
    process.exit(1);
  }
  const m = out.match(/Python (\d+)\.(\d+)/);
  if (!m) {
    console.error("Could not detect Python version.");
    process.exit(1);
  }
  const major = parseInt(m[1], 10);
  const minor = parseInt(m[2], 10);
  if (major < 3 || (major === 3 && minor < 10)) {
    console.error(`Python ${major}.${minor} found. Need 3.10+.`);
    process.exit(1);
  }
  console.log(`  Python ${major}.${minor} ✔`);
  return out.trim().split(" ")[1];
}

function getPythonExe() {
  if (execQuiet("python3 --version")) return "python3";
  if (execQuiet("python --version")) return "python";
  throw new Error("Python not found. Please install Python 3.10+.");
}

/* ── venv + deps ──────────────────────────────────────────── */

function ensureVenv(pythonExe) {
  if (!existsSync(VENV_DIR)) {
    console.log("\n  Creating Python virtual environment in ~/.maestro/venv ...");
    exec(`${pythonExe} -m venv "${VENV_DIR}"`);
  } else {
    console.log("  Virtual environment already exists.");
  }

  const pip = path.join(VENV_DIR, "bin", "pip");
  if (!existsSync(pip)) {
    throw new Error(`pip not found in ${VENV_DIR}/bin/`);
  }

  // Detect actual Python minor version for site-packages path
  const pyMinor = execQuiet(`"${pythonExe}" -c 'import sys; print(sys.version_info.minor)'`).trim();
  const sitePackages = path.join(VENV_DIR, "lib", `python3.${pyMinor}`, "site-packages");
  const pthFile = path.join(sitePackages, "maestro_runtime.pth");

  if (existsSync(sitePackages)) {
    mkdirSync(path.dirname(pthFile), { recursive: true });
    writeFileSync(pthFile, RUNTIME_DIR + "\n", "utf-8");
  }

  console.log("  Installing dependencies (this may take a minute) ...");
  exec(`"${pip}" install --upgrade pip`);
  exec(`"${pip}" install -r "${REQUIREMENTS_TXT}"`);
}

/* ── config files ────────────────────────────────────────── */

function buildConfig(provider, model, agentName, platforms, tokens) {
  const cfg = {
    model: {
      default: model,
      provider: provider === "ollama" ? "custom" : provider,
      base_url: provider === "ollama" ? "http://127.0.0.1:11434/v1" : undefined,
      api_key: provider === "ollama" ? "ollama" : undefined,
    },
    providers: {},
    credential_pool_strategies: {},
    toolsets: ["hermes-cli"],
    agent: {
      max_turns: 90,
      gateway_timeout: 1800,
      restart_drain_timeout: 60,
      service_tier: "",
      tool_use_enforcement: "auto",
      gateway_timeout_warning: 900,
    },
    terminal: {
      backend: "local",
      modal_mode: "auto",
      cwd: ".",
      timeout: 180,
      env_passthrough: [],
      persistent_shell: true,
    },
    compression: {
      enabled: true,
      threshold: 0.8,
      target_ratio: 0.2,
      protect_last_n: 20,
      summary_model: "",
      summary_provider: "auto",
      summary_base_url: null,
    },
    platforms: platforms.length > 0 ? platforms : undefined,
  };
  return cfg;
}

function writeYaml(obj, indent = 0) {
  let out = "";
  for (const [k, v] of Object.entries(obj)) {
    if (v === undefined) continue;
    const prefix = "  ".repeat(indent);
    if (v === null) {
      out += `${prefix}${k}: null\n`;
    } else if (typeof v === "boolean") {
      out += `${prefix}${k}: ${v}\n`;
    } else if (typeof v === "number") {
      out += `${prefix}${k}: ${v}\n`;
    } else if (typeof v === "string") {
      out += `${prefix}${k}: "${v}"\n`;
    } else if (Array.isArray(v)) {
      out += `${prefix}${k}:\n`;
      for (const item of v) out += `${prefix}  - ${item}\n`;
    } else if (typeof v === "object") {
      out += `${prefix}${k}:\n`;
      out += writeYaml(v, indent + 1);
    }
  }
  return out;
}

function writeEnvFile(tokens, provider, model) {
  const lines = ["# Maestro environment — auto-generated by maestro init", ""];
  if (tokens.OPENROUTER_API_KEY) lines.push(`OPENROUTER_API_KEY=${tokens.OPENROUTER_API_KEY}`);
  if (tokens.OPENAI_API_KEY)     lines.push(`OPENAI_API_KEY=${tokens.OPENAI_API_KEY}`);
  if (tokens.ANTHROPIC_API_KEY)  lines.push(`ANTHROPIC_API_KEY=${tokens.ANTHROPIC_API_KEY}`);
  if (tokens.OLLAMA_API_KEY)     lines.push(`OLLAMA_API_KEY=${tokens.OLLAMA_API_KEY}`);
  for (const p of PLATFORMS) {
    const tk = tokens[p.id];
    if (tk) {
      const envKey = p.envKey || `${p.id.toUpperCase()}_API_KEY`;
      lines.push(`${envKey}=${tk}`);
    }
  }
  lines.push("");
  writeFileSync(ENV_PATH, lines.join("\n"), "utf-8");
}

function writeTransportConfig(agentName) {
  const cfg = {
    agentId: agentName,
    version: "3.2",
    port: 3844,
    hermesApiUrl: "http://127.0.0.1:8642",
    hermesApiKey: "maestro-local-dev",
    conversation: "maestro",
    registryPath: REGISTRY_PATH,
  };
  writeFileSync(TRANSPORT_JSON, JSON.stringify(cfg, null, 2), "utf-8");
}

/* ── wizard flow ──────────────────────────────────────────── */

async function runWizard() {
  banner();

  /* 1. Python check */
  console.log("Step 1: Checking Python ...");
  checkPython();

  /* 2. Create ~/.maestro */
  console.log("\nStep 2: Creating ~/.maestro/ ...");
  mkdirSync(MAESTRO_DIR, { recursive: true });
  console.log("  Directory ready ✔");

  /* 3. Provider / model */
  console.log("\nStep 3: Choose your AI provider ");
  const providerNames = Object.values(PROVIDERS).map((p) => p.label);
  const providerIdx = await askChoice("Provider", providerNames);
  const providerKey = Object.keys(PROVIDERS)[providerIdx];
  const providerMeta = PROVIDERS[providerKey];

  let model = providerMeta.defaultModel;
  if (await confirm(`Use default model "${model}"? You can change it later.`)) {
    // default stays
  } else {
    model = await ask("Enter model name");
  }

  /* 4. Agent name */
  console.log("\nStep 4: Agent identity");
  const agentName = await ask("Agent name", "maestro-agent");

  /* 5. Platforms */
  console.log("\nStep 5: Messaging platforms");
  const enabledPlatforms = [];
  const platformTokens = {};

  for (const p of PLATFORMS) {
    if (await confirm(`Enable ${p.label}?`)) {
      enabledPlatforms.push(p.id);
      if (p.needsToken) {
        const token = await ask(p.tokenPrompt);
        platformTokens[p.id] = token;
      }
    }
  }

  if (enabledPlatforms.length === 0) {
    console.log("  No platforms selected — continuing in CLI-only mode.");
  }

  /* 6. API key for non-Ollama providers */
  const tokens = { ...platformTokens };
  if (providerMeta.needsKey) {
    const key = await ask(`Paste your ${providerMeta.label} API key`);
    if (providerKey === "openai") tokens.OPENAI_API_KEY = key;
    if (providerKey === "anthropic") tokens.ANTHROPIC_API_KEY = key;
  }

  /* 7. Build configs */
  console.log("\nStep 6: Writing configuration ...");
  const cfg = buildConfig(providerKey, model, agentName, enabledPlatforms, tokens);
  writeFileSync(CONFIG_PATH, writeYaml(cfg), "utf-8");
  writeEnvFile(tokens, providerKey, model);
  writeTransportConfig(agentName);
  console.log("  config.yaml ✔");
  console.log("  .env        ✔");
  console.log("  maestro_transport.json ✔");

  /* 8. Venv + deps */
  console.log("\nStep 7: Installing Python runtime ...");
  const pythonExe = getPythonExe();
  ensureVenv(pythonExe);

  /* 9. Gateway start script wrapper */
  console.log("\nStep 8: Preparing gateway ...");
  const startScript = path.join(MAESTRO_DIR, "start-gateway.sh");
  const logFile = path.join(MAESTRO_DIR, "gateway.log");
  const scriptContent = `#!/usr/bin/env bash
# Maestro gateway start script — auto-generated
set -e
cd "${RUNTIME_DIR}"
export HERMES_HOME="${MAESTRO_DIR}"
export PYTHONHOME=""
export PATH="${VENV_DIR}/bin:$PATH"
export CONFIG="${CONFIG_PATH}"
nohup python -m gateway.run "$@" > "${logFile}" 2>&1 &
echo $! > "${MAESTRO_DIR}/gateway.pid"
echo "Gateway started (PID $!)"
`;
  writeFileSync(startScript, scriptContent, "utf-8");
  execQuiet(`chmod +x "${startScript}"`);
  console.log("  start-gateway.sh ✔");

  /* 10. Final */
  console.log(`\n  ╔══════════════════════════════════════════════════════╗`);
  console.log(`  ║   Setup complete!                                    ║`);
  console.log(`  ║   Agent: ${agentName.padEnd(41)}║`);
  console.log(`  ║   Model: ${model.padEnd(41)}║`);
  console.log(`  ║   Config: ~/.maestro/config.yaml                     ║`);
  console.log(`  ╚══════════════════════════════════════════════════════╝\n`);

  const noStart = process.argv.includes("--no-start");
  if (noStart) {
    console.log("  Skipping auto-start (—no-start flag).");
    console.log("  To start the gateway, run:");
    console.log(`    bash ~/.maestro/start-gateway.sh`);
    console.log(`    tail -f ~/.maestro/gateway.log`);
  } else if (enabledPlatforms.includes("telegram")) {
    console.log("  Starting gateway with Telegram ...\n");
    exec(`bash "${startScript}"`);
    // Give it time to boot
    await new Promise((r) => setTimeout(r, 4000));
    const pid = execQuiet(`cat "${MAESTRO_DIR}/gateway.pid"`);
    if (pid) {
      const running = execQuiet(`kill -0 ${pid} 2>/dev/null && echo "ok"`);
      if (running === "ok") {
        console.log(`  ╔══════════════════════════════════════════════════════╗`);
        console.log(`  ║   Your agent is online!                              ║`);
        console.log(`  ║   Telegram: @${(platformTokens.telegram || "YourBot").split(":")[0].padEnd(32)}║`);
        console.log(`  ║   PID: ${pid.trim().padEnd(37)}║`);
        console.log(`  ║   Log:  ~/.maestro/gateway.log                       ║`);
        console.log(`  ╚══════════════════════════════════════════════════════╝\n`);
      } else {
        console.log("  ⚠ Gateway process exited unexpectedly.");
        console.log(`    tail -n 20 ~/.maestro/gateway.log`);
      }
    }
  } else {
    console.log("  To start the gateway later, run:");
    console.log(`    bash ~/.maestro/start-gateway.sh`);
  }

  closeReadline();
}

/* ── main guard ────────────────────────────────────────────── */

runWizard().catch((err) => {
  closeReadline();
  console.error("\nWizard failed:", err.message);
  process.exit(1);
});
