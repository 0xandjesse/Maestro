// ============================================================
// Maestro Protocol — Transport Service Entry Point
// ============================================================
// Boots the transport for all configured agents and keeps
// it running. Reads config from maestro.config.json.
//
// Run directly: node scripts/transport-service.mjs
// Or via Windows Task Scheduler for persistent operation.
// ============================================================

import { Maestro } from '../dist/index.js';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, '..');

// Load config
const configPath = resolve(repoRoot, 'maestro.config.json');
const config = JSON.parse(readFileSync(configPath, 'utf8'));

const hermesAgents = config.hermesAgents ?? [];

console.log(`[Maestro] Starting transport service — ${new Date().toISOString()}`);
console.log(`[Maestro] Config: ${configPath}`);
console.log(`[Maestro] OpenClaw agents: ${config.agents.map(a => a.agentId).join(', ')}`);
if (hermesAgents.length > 0) {
  console.log(`[Maestro] Hermes agents: ${hermesAgents.map(a => a.agentId).join(', ')}`);
}

const instances = [];

// Boot a Maestro instance for each configured OpenClaw agent
for (const agentCfg of config.agents) {
  const maestro = new Maestro({
    agentId: agentCfg.agentId,
    transport: agentCfg.transport,
    discovery: agentCfg.discovery,
    openclaw: agentCfg.openclaw,
  });

  await maestro.start();
  instances.push({ agentId: agentCfg.agentId, maestro });
  console.log(`[Maestro] ${agentCfg.agentId} online — port ${agentCfg.transport?.port ?? 3842} [openclaw]`);
}

// Boot a Maestro instance for each configured Hermes agent
// Hermes agents use a separate port range (3844+) and the Hermes adapter
let hermesPort = 3844;
for (const agentCfg of hermesAgents) {
  const port = agentCfg.transport?.port ?? hermesPort++;
  const maestro = new Maestro({
    agentId: agentCfg.agentId,
    transport: {
      port,
      registryPath: agentCfg.transport?.registryPath ?? '.maestro/registry.json',
    },
    discovery: agentCfg.discovery ?? { method: 'mdns' },
    hermes: {
      apiUrl: agentCfg.apiUrl,
      apiKey: agentCfg.apiKey,
      agentSessions: agentCfg.agentSessions,
    },
  });

  await maestro.start();
  instances.push({ agentId: agentCfg.agentId, maestro });
  console.log(`[Maestro] ${agentCfg.agentId} online — port ${port} [hermes]`);
}

console.log(`\n[Maestro] All agents online. Transport running. Press Ctrl+C to stop.\n`);

// Health check log every 5 minutes
setInterval(() => {
  console.log(`[Maestro] Heartbeat — ${new Date().toISOString()} — ${instances.length} agent(s) running`);
}, 5 * 60 * 1000);

// Graceful shutdown
const shutdown = async (signal) => {
  console.log(`\n[Maestro] ${signal} received — shutting down...`);
  for (const { agentId, maestro } of instances) {
    await maestro.stop();
    console.log(`[Maestro] ${agentId} stopped`);
  }
  process.exit(0);
};

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
