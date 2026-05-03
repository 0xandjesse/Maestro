#!/usr/bin/env node
/**
 * Maestro Protocol — Hermes-Agent Transport (Node.js)
 * ====================================================
 * Gives a Hermes-Agent instance a native Maestro identity.
 *
 * Runs as a sidecar alongside the Hermes gateway. Listens for
 * inbound MaestroMessages, delivers them to Hermes via the API
 * server (/v1/chat/completions), and POSTs the reply back to
 * the original sender's /message endpoint.
 *
 * This makes Hermes-Agent a full Maestro peer — not a target
 * accessed via a proxy, but a first-class participant that can:
 *   - Receive direct messages from any Maestro agent
 *   - Participate in shared Blackboards
 *   - Be discovered via the shared registry file
 *   - Route replies back as MaestroMessages
 *
 * Usage:
 *   node maestro-transport.mjs [--config maestro_transport.json]
 *
 * Requirements:
 *   Node.js >= 18 (built-in fetch + http)
 *   No npm install needed.
 *
 * Config (maestro_transport.json):
 *   {
 *     "agentId": "hermes-lex",
 *     "port": 3844,
 *     "hermesApiUrl": "http://127.0.0.1:8642",
 *     "hermesApiKey": "maestro-local-dev",
 *     "conversation": "maestro",
 *     "registryPath": "/home/andjesse/.maestro/registry.json",
 *     "version": "3.2",
 *     "knownPeers": {
 *       "songbird": "http://10.0.2.2:3842/message"
 *     }
 *   }
 */

import http from 'http';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ─── Logging ──────────────────────────────────────────────────────────────────

function log(msg) {
  const ts = new Date().toTimeString().slice(0, 8);
  console.log(`[${ts}] [maestro] ${msg}`);
}

function logError(msg) {
  const ts = new Date().toTimeString().slice(0, 8);
  console.error(`[${ts}] [maestro] ERROR: ${msg}`);
}

// ─── Config ───────────────────────────────────────────────────────────────────

const DEFAULT_CONFIG = {
  agentId: 'hermes-lex',
  port: 3844,
  hermesApiUrl: 'http://127.0.0.1:8642',
  hermesApiKey: 'maestro-local-dev',
  conversation: 'maestro',
  registryPath: '.maestro/registry.json',
  version: '3.2',
  knownPeers: {},
};

function loadConfig(configPath) {
  // Resolve config path relative to this script's directory
  const resolved = path.isAbsolute(configPath)
    ? configPath
    : path.resolve(__dirname, configPath);

  if (fs.existsSync(resolved)) {
    try {
      const raw = fs.readFileSync(resolved, 'utf8');
      const loaded = JSON.parse(raw);
      return { ...DEFAULT_CONFIG, ...loaded };
    } catch (e) {
      logError(`Failed to parse config at ${resolved}: ${e.message}`);
      process.exit(1);
    }
  }
  log(`Config not found at ${resolved} — using defaults`);
  return { ...DEFAULT_CONFIG };
}

// ─── Registry (file-based, compatible with JS LocalRegistry) ──────────────────

class LocalRegistry {
  constructor(registryPath) {
    // Resolve relative paths from script directory
    this.path = path.isAbsolute(registryPath)
      ? registryPath
      : path.resolve(__dirname, registryPath);

    fs.mkdirSync(path.dirname(this.path), { recursive: true });
  }

  _load() {
    if (fs.existsSync(this.path)) {
      try {
        return JSON.parse(fs.readFileSync(this.path, 'utf8'));
      } catch {
        return [];
      }
    }
    return [];
  }

  _save(data) {
    fs.writeFileSync(this.path, JSON.stringify(data, null, 2), 'utf8');
  }

  register(agentId, webhookEndpoint, capabilities = []) {
    const data = this._load().filter(e => e.agentId !== agentId);
    data.push({
      agentId,
      webhookEndpoint,
      capabilities,
      registeredAt: Date.now(),
      lastSeen: Date.now(),
    });
    this._save(data);
    log(`Registered ${agentId} at ${webhookEndpoint}`);
  }

  lookup(agentId) {
    return this._load().find(e => e.agentId === agentId) ?? null;
  }

  unregister(agentId) {
    const data = this._load().filter(e => e.agentId !== agentId);
    this._save(data);
  }
}

// ─── Hermes Client ────────────────────────────────────────────────────────────

class HermesClient {
  constructor(apiUrl, apiKey) {
    this.apiUrl = apiUrl.replace(/\/$/, '');
    this.headers = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`,
    };
  }

  _formatPrompt(message) {
    const lines = [
      '[Maestro Protocol — Inbound Message]',
      `From: ${message.sender?.agentId ?? 'unknown'}`,
      `Type: ${message.type ?? 'direct'}`,
    ];
    if (message.stageId) lines.push(`Connection: ${message.stageId}`);
    lines.push('');
    lines.push(message.content ?? '');
    return lines.join('\n');
  }

  async sendAndComplete(message) {
    const prompt = this._formatPrompt(message);

    const res = await fetch(`${this.apiUrl}/v1/chat/completions`, {
      method: 'POST',
      headers: this.headers,
      body: JSON.stringify({
        model: 'hermes-agent',
        messages: [{ role: 'user', content: prompt }],
        stream: false,
      }),
      signal: AbortSignal.timeout(120_000),
    });

    if (!res.ok) {
      const text = await res.text();
      logError(`Chat completions failed ${res.status}: ${text}`);
      return null;
    }

    const data = await res.json();
    const output = data?.choices?.[0]?.message?.content ?? null;
    if (output) log(`Response received: ${output.slice(0, 80)}...`);
    return output;
  }

  async healthCheck() {
    try {
      const res = await fetch(`${this.apiUrl}/health`, {
        signal: AbortSignal.timeout(5_000),
      });
      return res.ok;
    } catch {
      return false;
    }
  }
}

// ─── HTTP helpers ─────────────────────────────────────────────────────────────

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => (body += chunk));
    req.on('end', () => resolve(body));
    req.on('error', reject);
  });
}

function sendJSON(res, status, data) {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

// ─── Transport ────────────────────────────────────────────────────────────────

class MaestroTransport {
  constructor(config) {
    this.config = config;
    this.agentId = config.agentId;
    this.port = config.port;
    this.hermes = new HermesClient(config.hermesApiUrl, config.hermesApiKey);
    this.registry = new LocalRegistry(config.registryPath);
    this.startedAt = null;
    this.server = http.createServer((req, res) => this._router(req, res));
  }

  async _router(req, res) {
    const url = new URL(req.url, `http://localhost`);

    if (req.method === 'GET' && url.pathname === '/health') {
      return this._handleHealth(req, res);
    }

    if (req.method === 'POST' &&
        (url.pathname === '/maestro/webhook' || url.pathname === '/message')) {
      return this._handleMessage(req, res);
    }

    if (req.method === 'GET' && url.pathname.startsWith('/connections/')) {
      const connectionId = url.pathname.split('/connections/')[1];
      return this._handleConnectionGet(req, res, connectionId);
    }

    sendJSON(res, 404, { error: 'Not found' });
  }

  _handleHealth(_req, res) {
    sendJSON(res, 200, {
      ok: true,
      agentId: this.agentId,
      platform: 'hermes-agent',
      uptime: this.startedAt ? Date.now() - this.startedAt : 0,
    });
  }

  async _handleMessage(req, res) {
    let message;
    try {
      const body = await readBody(req);
      message = JSON.parse(body);
    } catch {
      return sendJSON(res, 400, { accepted: false, reason: 'Invalid JSON' });
    }

    if (!message.id || !message.type || !message.sender) {
      return sendJSON(res, 400, { accepted: false, reason: 'Invalid message format' });
    }

    log(`Inbound message from ${message.sender?.agentId} type=${message.type}`);

    // Accept immediately, process async
    this._processMessage(message).catch(e => logError(`Unhandled error: ${e.message}`));
    sendJSON(res, 200, { accepted: true });
  }

  async _processMessage(message) {
    try {
      const output = await this.hermes.sendAndComplete(message);
      if (!output) {
        log('No output from Hermes — not routing reply');
        return;
      }

      const senderId = message.sender?.agentId;
      const senderReg = this.registry.lookup(senderId);
      if (!senderReg) {
        log(`Sender ${senderId} not in registry — cannot route reply`);
        return;
      }

      const reply = {
        id: crypto.randomUUID(),
        type: 'direct',
        content: output,
        sender: { agentId: this.agentId },
        recipient: senderId,
        timestamp: Date.now(),
        version: this.config.version,
        ...(message.stageId ? { stageId: message.stageId } : {}),
      };

      const endpoint = senderReg.webhookEndpoint;
      log(`Routing reply to ${senderId} at ${endpoint}: ${output.slice(0, 80)}...`);

      const replyRes = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(reply),
        signal: AbortSignal.timeout(10_000),
      });

      if (replyRes.ok) {
        log(`Reply delivered to ${senderId}`);
      } else {
        logError(`Reply delivery failed: ${replyRes.status}`);
      }
    } catch (e) {
      logError(`Message processing error: ${e.message}`);
    }
  }

  _handleConnectionGet(_req, res, connectionId) {
    // Stub — full Connection support in a future version
    sendJSON(res, 200, {
      id: connectionId,
      status: 'active',
      agentId: this.agentId,
    });
  }

  async start() {
    // Health-check Hermes API before binding
    const ok = await this.hermes.healthCheck();
    if (!ok) {
      logError(`Hermes API not reachable at ${this.hermes.apiUrl} — is the gateway running?`);
      process.exit(1);
    }
    log(`Hermes API reachable at ${this.hermes.apiUrl}`);

    // Register self in local registry
    const endpoint = `http://0.0.0.0:${this.port}/maestro/webhook`;
    this.registry.register(this.agentId, endpoint);

    // Seed known peers (static cross-host endpoints)
    for (const [peerId, peerEndpoint] of Object.entries(this.config.knownPeers ?? {})) {
      this.registry.register(peerId, peerEndpoint);
      log(`Seeded known peer: ${peerId} at ${peerEndpoint}`);
    }

    this.startedAt = Date.now();

    await new Promise((resolve, reject) => {
      this.server.listen(this.port, '0.0.0.0', () => resolve());
      this.server.on('error', reject);
    });

    log(`${this.agentId} listening on 0.0.0.0:${this.port}`);
    log(`Hermes API: ${this.hermes.apiUrl}`);
    log('Ready.');
  }

  async stop() {
    this.registry.unregister(this.agentId);
    await new Promise(resolve => this.server.close(resolve));
    log('Stopped.');
  }
}

// ─── Entry point ──────────────────────────────────────────────────────────────

const args = process.argv.slice(2);
const configIdx = args.indexOf('--config');
const configPath = configIdx !== -1 ? args[configIdx + 1] : 'maestro_transport.json';

const config = loadConfig(configPath);
log(`Starting Maestro transport for ${config.agentId}`);

const transport = new MaestroTransport(config);
await transport.start();

log('Transport running. Press Ctrl+C to stop.');

process.on('SIGINT', async () => {
  log('SIGINT received — shutting down...');
  await transport.stop();
  process.exit(0);
});

process.on('SIGTERM', async () => {
  log('SIGTERM received — shutting down...');
  await transport.stop();
  process.exit(0);
});

// Keep alive
setInterval(() => {}, 1 << 30);
