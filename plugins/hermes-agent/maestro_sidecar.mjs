#!/usr/bin/env node
// ============================================================
// Maestro Protocol — Hermes-Agent Sidecar
// ============================================================
//
// Lightweight HTTP bridge that the Python Hermes-Agent plugin
// calls. Wraps the Maestro SDK and exposes a simple REST API.
//
// Environment variables (set by maestro_plugin.py):
//   MAESTRO_AGENT_ID       Agent identity
//   MAESTRO_PORT           Port to listen on (default 3843)
//   MAESTRO_BLACKBOARD_PATH  SQLite path (optional)
//   MAESTRO_DISCOVERY      mdns | file | none
//   MAESTRO_REGISTRY_PATH  File registry path (for discovery=file)
//
// This script is self-contained — it uses the @maestro-protocol/core
// package from node_modules (installed alongside the Maestro repo).
// ============================================================

import { createServer } from 'http';
import { Maestro } from '@maestro-protocol/core';

const agentId = process.env.MAESTRO_AGENT_ID ?? 'hermes-agent';
const port = parseInt(process.env.MAESTRO_PORT ?? '3843', 10);
const blackboardPath = process.env.MAESTRO_BLACKBOARD_PATH || undefined;
const discoveryMethod = process.env.MAESTRO_DISCOVERY ?? 'mdns';
const registryPath = process.env.MAESTRO_REGISTRY_PATH || './.maestro/registry.json';

// ============================================================
// Boot Maestro
// ============================================================

const maestro = new Maestro({
  agentId,
  // Sidecar itself doesn't need a webhook server — the Python
  // side does HTTP polling. But we keep it so agents can send
  // to Hermes directly if needed.
  webhookPort: port + 1,
  blackboardPath,
  discovery: discoveryMethod === 'none' ? undefined : {
    method: discoveryMethod,
    filePath: registryPath,
  },
});

await maestro.start();
console.error(`[maestro-sidecar] started — agentId=${agentId} sidecar-port=${port}`);

// ============================================================
// HTTP REST bridge
// ============================================================

async function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', chunk => { data += chunk; });
    req.on('end', () => {
      try { resolve(data ? JSON.parse(data) : {}); }
      catch (e) { reject(e); }
    });
    req.on('error', reject);
  });
}

function send(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(payload);
}

const server = createServer(async (req, res) => {
  if (req.method === 'GET' && req.url === '/health') {
    return send(res, 200, { ok: true, agentId, port });
  }

  if (req.method !== 'POST') {
    return send(res, 405, { error: 'method_not_allowed' });
  }

  let body;
  try {
    body = await readBody(req);
  } catch {
    return send(res, 400, { error: 'invalid_json' });
  }

  try {
    const result = await route(req.url, body);
    send(res, 200, result);
  } catch (err) {
    send(res, 500, { error: String(err) });
  }
});

server.listen(port, () => {
  console.error(`[maestro-sidecar] REST bridge listening on port ${port}`);
});

// ============================================================
// Route handlers
// ============================================================

async function route(url, body) {
  switch (url) {

    // --------------------------------------------------------
    case '/venue/create': {
      const { name, roles } = body;
      let handle;
      if (roles && roles.length >= 2) {
        const reportingChain = {};
        for (let i = 1; i < roles.length; i++) {
          reportingChain[roles[i]] = roles[i - 1];
        }
        handle = maestro.createHierarchicalVenue(name, roles, reportingChain);
      } else {
        handle = maestro.createOpenVenue(name);
      }
      const info = handle.getVenueInfo();
      return {
        venueId: info.id,
        name: info.name,
        hostId: info.hostId,
        entryMode: info.rules.entryMode,
        hierarchy: info.rules.hierarchy ?? null,
        membersCount: handle.getMembers().length,
        webhookEndpoint: maestro.webhookEndpoint,
      };
    }

    // --------------------------------------------------------
    case '/venue/join': {
      const { venueId } = body;
      const response = maestro.join(venueId);
      if (response.status === 'accepted') {
        return {
          status: 'accepted',
          venueId,
          role: response.role,
          supervisorId: response.supervisorId ?? null,
        };
      }
      return { status: response.status, venueId, reason: response.reason };
    }

    // --------------------------------------------------------
    case '/venue/list': {
      const venues = maestro.listVenues().map(h => {
        const info = h.getVenueInfo();
        return {
          venueId: info.id,
          name: info.name,
          hostId: info.hostId,
          status: info.status,
          membersCount: h.getMembers().length,
        };
      });
      return { venues, count: venues.length };
    }

    // --------------------------------------------------------
    case '/message/send': {
      const { venueId, content, type = 'direct', recipientId } = body;
      const handle = maestro.getVenue(venueId);
      if (!handle) return { error: `Not a member of Venue ${venueId}` };

      let msg;
      switch (type) {
        case 'broadcast': msg = await handle.broadcast(content); break;
        case 'report':    msg = await handle.reportTo(content); break;
        case 'assign':
          if (!recipientId) return { error: 'recipientId required for assign' };
          msg = await handle.assignTo(recipientId, content);
          break;
        default:
          if (!recipientId) return { error: 'recipientId required for direct' };
          msg = await handle.send(recipientId, content);
      }
      return { messageId: msg.id, type: msg.type, recipient: msg.recipient };
    }

    // --------------------------------------------------------
    case '/blackboard/set': {
      const { venueId, key, value } = body;
      const handle = maestro.getVenue(venueId);
      if (!handle) return { error: `Not a member of Venue ${venueId}` };
      await handle.blackboard.set(key, value, agentId);
      return { key, written: true };
    }

    // --------------------------------------------------------
    case '/blackboard/get': {
      const { venueId, key, prefix } = body;
      const handle = maestro.getVenue(venueId);
      if (!handle) return { error: `Not a member of Venue ${venueId}` };

      if (key) {
        const entry = await handle.blackboard.getEntry(key);
        if (!entry) return { key, value: null, found: false };
        return { key: entry.key, value: entry.value, writtenBy: entry.writtenBy, version: entry.version, found: true };
      }

      const keys = await handle.blackboard.list(prefix);
      return { keys, count: keys.length };
    }

    // --------------------------------------------------------
    case '/peers/list': {
      const peers = maestro.peers.map(p => ({
        agentId: p.agentId,
        endpoint: p.webhookEndpoint,
        capabilities: p.capabilities ?? [],
        lastSeen: p.lastSeen,
      }));
      return { peers, count: peers.length, selfEndpoint: maestro.webhookEndpoint };
    }

    default:
      return { error: `unknown_route: ${url}` };
  }
}

// ============================================================
// Graceful shutdown
// ============================================================

async function shutdown() {
  console.error('[maestro-sidecar] shutting down...');
  server.close();
  await maestro.stop();
  process.exit(0);
}

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
