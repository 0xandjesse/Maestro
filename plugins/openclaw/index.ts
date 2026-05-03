// ============================================================
// Maestro Protocol — OpenClaw Plugin
// ============================================================
//
// Gives OpenClaw agents Maestro presence: discover peers,
// create/join Venues, share Blackboards, and send structured
// messages across process boundaries.
//
// Multi-agent architecture: one Maestro instance per agent,
// keyed by agentId. Each instance gets its own webhook port.
//
// Config (plugins.entries.maestro-protocol.config):
//   agents:
//     - agentId: "songbird"
//       webhookPort: 3842
//       discovery: "mdns"        # mdns | file | none
//       blackboardPath: ""       # optional SQLite path
//       registryPath: ""         # required when discovery=file
//     - agentId: "lexicon"
//       webhookPort: 3843
//       discovery: "mdns"
//
// Legacy single-agent config (still supported):
//   agentId: "songbird"
//   webhookPort: 3842
//   discovery: "mdns"
// ============================================================

import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { readFileSync, existsSync } from 'fs';

// requestHeartbeatNow is a runtime-injected module — must be imported dynamically
// inside the plugin host context, not as a static top-level import.
let _requestHeartbeatNow: ((opts: { sessionKey?: string; reason?: string }) => void) | null = null;
async function getHeartbeatFn() {
  if (_requestHeartbeatNow) return _requestHeartbeatNow;
  try {
    const mod = await import('openclaw/infra/heartbeat-wake') as any;
    _requestHeartbeatNow = mod.requestHeartbeatNow;
  } catch {
    // Not available in this host context — no-op
    _requestHeartbeatNow = () => {};
  }
  return _requestHeartbeatNow!;
}

// ============================================================
// Types
// ============================================================

interface AgentMaestroConfig {
  agentId: string;
  webhookPort?: number;
  blackboardPath?: string;
  discovery?: "mdns" | "file" | "none";
  registryPath?: string;
}

interface HermesAgentConfig {
  agentId: string;
  apiUrl: string;
  apiKey: string;
  transport?: { port?: number };
  agentSessions?: Record<string, string>;
}

interface MaestroInstance {
  maestro: any;
  agentId: string;
  ready: boolean;
  webhookPort: number;
  registryPath?: string;
  webhookEndpoint: string;
  type?: 'openclaw' | 'hermes';
}

// ============================================================
// Global message event bus — Concerto listens on this
// ============================================================
type MessageEventListener = (event: MessageEvent) => void;
interface MessageEvent {
  ts: number;
  from: string;
  to: string;
  type: string;
  content: string;
  stageId?: string;
}
const _messageListeners: Set<MessageEventListener> = new Set();
const _messageHistory: MessageEvent[] = [];
const MAX_HISTORY = 500;

function emitMessage(event: MessageEvent) {
  _messageHistory.push(event);
  if (_messageHistory.length > MAX_HISTORY) _messageHistory.shift();
  for (const fn of _messageListeners) {
    try { fn(event); } catch { /* ignore */ }
  }
}

// ============================================================
// Runtime state — Map keyed by agentId
// ============================================================

const _instances = new Map<string, MaestroInstance>();

function getInstance(agentId: string): MaestroInstance | undefined {
  return _instances.get(agentId);
}

function getDefaultInstance(): MaestroInstance | undefined {
  // Return first ready instance, or first instance overall
  for (const inst of _instances.values()) {
    if (inst.ready) return inst;
  }
  return _instances.values().next().value;
}

function resolveInstance(agentId?: string): MaestroInstance | undefined {
  if (agentId) return getInstance(agentId);
  return getDefaultInstance();
}

// ============================================================
// Plugin entry
// ============================================================

export default definePluginEntry({
  id: "maestro-protocol",
  name: "Maestro Protocol",
  description: "Open agent coordination — Venues, Blackboards, and multi-agent messaging",

  register(api) {
    const config = (api.pluginConfig ?? {}) as {
      // Multi-agent format
      agents?: AgentMaestroConfig[];
      // Hermes VM agents
      hermesAgents?: HermesAgentConfig[];
      // Legacy single-agent format
      agentId?: string;
      webhookPort?: number;
      blackboardPath?: string;
      discovery?: "mdns" | "file" | "none";
      registryPath?: string;
    };

    const hermesAgentConfigs: HermesAgentConfig[] = config.hermesAgents ?? [];

    // Normalize to array format regardless of input
    const agentConfigs: AgentMaestroConfig[] = config.agents ?? [
      {
        agentId: config.agentId ?? (api.config as any)?.agent?.name ?? "songbird",
        webhookPort: config.webhookPort ?? 3842,
        blackboardPath: config.blackboardPath,
        discovery: config.discovery ?? "mdns",
        registryPath: config.registryPath,
      },
    ];

    // --------------------------------------------------------
    // Background service: start one Maestro instance per agent
    // --------------------------------------------------------
    api.registerService({
      id: "maestro-webhook",
      async start() {
        const { Maestro } = await import(
          "@maestro-protocol/core"
        ) as any;

        // ---- Boot Hermes VM agents ----
        for (const hcfg of hermesAgentConfigs) {
          const port = hcfg.transport?.port ?? 3844;
          const whEndpoint = `http://localhost:${port}/maestro/webhook`;
          _instances.set(hcfg.agentId, { maestro: null, agentId: hcfg.agentId, ready: false, webhookPort: port, webhookEndpoint: whEndpoint, type: 'hermes' });
          try {
            const defaultRegistryPath = 'C:\\Users\\there\\Projects\\Maestro\\maestro-protocol\\.maestro\\registry.json';
            const defaultDbPath = 'C:\\Users\\there\\Projects\\Maestro\\maestro-protocol\\.maestro\\connections.db';
            const maestro = new Maestro({
              agentId: hcfg.agentId,
              transport: { port, registryPath: defaultRegistryPath, dbPath: defaultDbPath },
              hermes: {
                apiUrl: hcfg.apiUrl,
                apiKey: hcfg.apiKey,
                agentSessions: hcfg.agentSessions,
                awaitResponse: true,
                responseTimeoutMs: 90000,
              },
            });
            await maestro.start();
            _instances.set(hcfg.agentId, { maestro, agentId: hcfg.agentId, ready: true, webhookPort: port, webhookEndpoint: whEndpoint, type: 'hermes' });
            api.logger.info(`Maestro Hermes adapter started — agentId=${hcfg.agentId} port=${port}`);
            // Emit inbound messages to Concerto feed
            maestro.onMessage('*', (msg: any) => {
              emitMessage({
                ts: Date.now(),
                from: msg.sender?.agentId ?? 'unknown',
                to: hcfg.agentId,
                type: msg.type,
                content: msg.content ?? JSON.stringify(msg),
                stageId: msg.stageId,
              });
            });
          } catch (err) {
            api.logger.error(`Maestro Hermes adapter failed for agent ${hcfg.agentId}: ${err}`);
          }
        }

        // ---- Boot OpenClaw agents ----
        for (const cfg of agentConfigs) {
          const { agentId, webhookPort = 3842, blackboardPath, discovery = "mdns", registryPath } = cfg;

          const whEndpoint = `http://localhost:${webhookPort}/maestro/webhook`;
          // Initialize slot immediately so tools can report "starting"
          _instances.set(agentId, { maestro: null, agentId, ready: false, webhookPort, registryPath, webhookEndpoint: whEndpoint });

          try {
            // Use transport config to boot the HTTP server on webhookPort.
            // Use absolute paths so the plugin works from any CWD.
            const defaultRegistryPath = 'C:\\Users\\there\\Projects\\Maestro\\maestro-protocol\\.maestro\\registry.json';
            const defaultDbPath = 'C:\\Users\\there\\Projects\\Maestro\\maestro-protocol\\.maestro\\connections.db';
            const maestro = new Maestro({
              agentId,
              webhookPort,
              transport: {
                port: webhookPort,
                registryPath: registryPath ?? defaultRegistryPath,
                dbPath: defaultDbPath,
              },
              blackboardPath: blackboardPath || undefined,
            });
            await maestro.start();
            _instances.set(agentId, { maestro, agentId, ready: true, webhookPort, registryPath, webhookEndpoint: whEndpoint });
            api.logger.info(`Maestro started — agentId=${agentId} port=${webhookPort}`);
            // Mark as openclaw type
            _instances.set(agentId, { maestro, agentId, ready: true, webhookPort, registryPath, webhookEndpoint: whEndpoint, type: 'openclaw' });

            // Wire incoming messages into the agent's active session and wake it.
            //
            // Routing by message type:
            //   direct  → persistent named session (session:agentId-from) — conversational,
            //             observable in Concerto, context preserved across exchanges
            //   other   → isolated turn (fire-and-forget) — handoff/task passing,
            //             dumb pipe, human only cares about the final deliverable
            maestro.onMessage('*', (msg: any) => {
              try {
                const from = msg.sender?.agentId ?? msg.from ?? 'unknown';
                const content = msg.content ?? msg.text ?? JSON.stringify(msg);
                const venueCtx = msg.venueId ? ` (Venue: ${msg.venueId})` : '';
                const text = `[Maestro message from ${from}${venueCtx}]: ${content}`;

                const gatewayUrl = 'http://127.0.0.1:18789';
                const hookToken = '06fe84970c2ba322f6e59e007145f015f862be85e72823265fad2b3b8ced1069';
                const isDirect = msg.type === 'direct';

                if (isDirect) {
                  // Conversational: route to persistent named session so context is preserved
                  // and the exchange is observable. Session key: session:agentId:from
                  const sessionKey = `session:${agentId}:${from}`;
                  fetch(`${gatewayUrl}/hooks/agent`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${hookToken}` },
                    body: JSON.stringify({
                      message: text,
                      agentId,
                      name: `Maestro from ${from}`,
                      wakeMode: 'now',
                      // Direct messages: use agent's native model (no override)
                      // so conversational turns use the right model (Sonnet for songbird, etc.)
                      sessionKey,
                    }),
                    signal: AbortSignal.timeout(5000),
                  }).then(r => {
                    if (r.ok) api.logger.info(`Maestro: routed direct message to persistent session ${sessionKey} (from ${from})`);
                    else api.logger.warn(`Maestro: hooks API rejected for direct message: ${r.status}`);
                  }).catch(e => {
                    api.logger.warn(`Maestro: hooks API failed for direct message (${e.message}), falling back to enqueue`);
                    api.runtime.system.enqueueSystemEvent(text, { sessionKey });
                    getHeartbeatFn().then(fn => fn({ sessionKey, reason: 'maestro:inbound' }));
                  });
                } else {
                  // Handoff/task: isolated turn, fire-and-forget, cheap model
                  fetch(`${gatewayUrl}/hooks/agent`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${hookToken}` },
                    body: JSON.stringify({
                      message: text,
                      agentId,
                      name: `Maestro from ${from}`,
                      wakeMode: 'now',
                      // Handoff/isolated turns: cheap model, no Anthropic tokens
                      model: 'ollama/kimi-k2.5:cloud',
                    }),
                    signal: AbortSignal.timeout(5000),
                  }).then(r => {
                    if (r.ok) api.logger.info(`Maestro: fired isolated turn for ${msg.type} message (from ${from})`);
                    else api.logger.warn(`Maestro: hooks API rejected for ${msg.type} message: ${r.status}`);
                  }).catch(e => {
                    api.logger.warn(`Maestro: hooks API failed for ${msg.type} message (${e.message}), falling back to enqueue`);
                    const sessionKey = `agent:${agentId}:main`;
                    api.runtime.system.enqueueSystemEvent(text, { sessionKey });
                    getHeartbeatFn().then(fn => fn({ sessionKey, reason: 'maestro:inbound' }));
                  });
                }

                api.logger.info(`Maestro: dispatched ${msg.type} message (from ${from})`);
                // Emit to Concerto feed
                emitMessage({ ts: Date.now(), from, to: agentId, type: msg.type, content, stageId: msg.venueId ?? msg.stageId });
              } catch (err) {
                api.logger.error(`Maestro: failed to inject inbound message: ${err}`);
              }
            });
          } catch (err) {
            api.logger.error(`Maestro failed to start for agent ${agentId}: ${err}`);
            _instances.set(agentId, { maestro: null, agentId, ready: false, webhookPort, registryPath, webhookEndpoint: whEndpoint });
          }
        }
      },

      async stop() {
        for (const [agentId, inst] of _instances) {
          if (inst.maestro) {
            try {
              await inst.maestro.stop();
              api.logger.info(`Maestro stopped — agentId=${agentId}`);
            } catch (err) {
              api.logger.error(`Maestro stop error for agent ${agentId}: ${err}`);
            }
          }
        }
        _instances.clear();
      },
    });

    // --------------------------------------------------------
    // Tool: maestro_status
    // --------------------------------------------------------
    api.registerTool(
      {
        name: "maestro_status",
        label: "Maestro Status",
        description: "Show the status of all Maestro agent instances running in this gateway.",
        parameters: {
          type: "object" as const,
          properties: {},
          additionalProperties: false,
        },
        async execute(_id, _params) {
          const statuses = [..._instances.entries()].map(([agentId, inst]) => {
            // Count peers from registry file if available
            let peersDiscovered = 0;
            if (inst.registryPath && existsSync(inst.registryPath)) {
              try {
                const reg = JSON.parse(readFileSync(inst.registryPath, 'utf8'));
                peersDiscovered = reg.filter((r: any) => r.agentId !== agentId).length;
              } catch { /* ignore */ }
            }
            return {
              agentId,
              ready: inst.ready,
              webhookEndpoint: inst.webhookEndpoint,
              peersDiscovered,
              registryPath: inst.registryPath,
            };
          });
          return ok({ instances: statuses, count: statuses.length });
        },
      }
    );

    // --------------------------------------------------------
    // Tool: maestro_peers
    // --------------------------------------------------------
    api.registerTool(
      {
        name: "maestro_peers",
        label: "Maestro Peers",
        description:
          "List Maestro agents discovered on the local network. Use agentId to select which agent instance to query (defaults to first ready instance).",
        parameters: {
          type: "object" as const,
          properties: {
            agentId: { type: "string", description: "Which agent instance to query (optional)" },
          },
          additionalProperties: false,
        },
        async execute(_id, params: any) {
          const inst = resolveInstance(params.agentId);
          if (!inst?.ready) return error(notReadyMsg(params.agentId));
          // Read peers from the registry file
          let peers: any[] = [];
          if (inst.registryPath && existsSync(inst.registryPath)) {
            try {
              const reg = JSON.parse(readFileSync(inst.registryPath, 'utf8'));
              peers = reg.filter((r: any) => r.agentId !== inst.agentId);
            } catch { /* ignore */ }
          }
          // Also check SDK registry as fallback
          if (peers.length === 0) {
            const registry = (inst.maestro as any)?.registry;
            if (registry?.listActive) {
              peers = (registry.listActive(120_000) as any[]).filter((p: any) => p.agentId !== inst.agentId);
            }
          }
          return ok({
            agentId: inst.agentId,
            peers: peers.map((p: any) => ({
              agentId: p.agentId,
              endpoint: p.webhookEndpoint,
              capabilities: p.capabilities ?? [],
              lastSeen: p.lastSeen,
            })),
            count: peers.length,
            selfEndpoint: inst.webhookEndpoint,
          });
        },
      }
    );

    // --------------------------------------------------------
    // Tool: maestro_venue_create
    // --------------------------------------------------------
    api.registerTool(
      {
        name: "maestro_venue_create",
        label: "Create Maestro Venue",
        description:
          "Create a Maestro Venue — a structured space for multi-agent coordination with a shared Blackboard.",
        parameters: {
          type: "object" as const,
          properties: {
            agentId: { type: "string", description: "Which agent instance to use (optional)" },
            name: { type: "string", description: "Human-readable Venue name" },
            roles: {
              type: "array",
              items: { type: "string" },
              description: 'Hierarchy roles from highest to lowest, e.g. ["lead","worker"]. Omit for flat peer Venue.',
            },
          },
          required: ["name"],
          additionalProperties: false,
        },
        async execute(_id, params: any) {
          const inst = resolveInstance(params.agentId);
          if (!inst?.ready) return error(notReadyMsg(params.agentId));

          let handle;
          if (params.roles && params.roles.length >= 2) {
            const reportingChain: Record<string, string> = {};
            for (let i = 1; i < params.roles.length; i++) {
              reportingChain[params.roles[i]] = params.roles[i - 1];
            }
            // v0.2.0 API: openHierarchicalConnection
            handle = inst.maestro.openHierarchicalConnection(params.name, params.roles, reportingChain);
          } else {
            // v0.2.0 API: openConnection
            handle = inst.maestro.openConnection(params.name);
          }

          const info = handle.getConnectionInfo();
          return ok({
            agentId: inst.agentId,
            venueId: info.id,
            name: info.name,
            hostId: info.hostAgentId ?? info.hostId,
            entryMode: info.rules?.entryMode ?? 'open',
            membersCount: handle.getMembers().length,
            webhookEndpoint: inst.webhookEndpoint,
          });
        },
      }
    );

    // --------------------------------------------------------
    // Tool: maestro_venue_join
    // --------------------------------------------------------
    api.registerTool(
      {
        name: "maestro_venue_join",
        label: "Join Maestro Venue",
        description: "Join an existing Maestro Venue by ID. For same-process joins, also provide hostAgentId.",
        parameters: {
          type: "object" as const,
          properties: {
            agentId: { type: "string", description: "The joining agent's instance (optional)" },
            venueId: { type: "string", description: "ID of the Venue to join" },
            hostAgentId: {
              type: "string",
              description: "Agent ID of the Venue host (for same-process joins — avoids HTTP round-trip)",
            },
          },
          required: ["venueId"],
          additionalProperties: false,
        },
        async execute(_id, params: any) {
          const inst = resolveInstance(params.agentId);
          if (!inst?.ready) return error(notReadyMsg(params.agentId));

          // v0.2.0: connectionManager is the right property
          let hostManager: any = undefined;
          if (params.hostAgentId) {
            const hostInst = getInstance(params.hostAgentId);
            if (!hostInst?.ready) return error(`Host agent "${params.hostAgentId}" is not ready`);
            hostManager = hostInst.maestro.connectionManager;
          }

          const response = inst.maestro.join(params.venueId, hostManager);
          if (response.status === "accepted") {
            return ok({ status: "accepted", agentId: inst.agentId, venueId: params.venueId, role: response.role });
          }
          return response.status === "pending"
            ? ok({ status: "pending", agentId: inst.agentId, venueId: params.venueId })
            : error(`Join rejected: ${response.reason ?? "unknown"}`);
        },
      }
    );

    // --------------------------------------------------------
    // Tool: maestro_send
    // --------------------------------------------------------
    api.registerTool(
      {
        name: "maestro_send",
        label: "Maestro Send",
        description:
          "Send a Maestro message in a Venue. Types: direct (to one agent), broadcast (all), report (to supervisor), assign (to subordinate).",
        parameters: {
          type: "object" as const,
          properties: {
            agentId: { type: "string", description: "Sending agent instance (optional)" },
            venueId: { type: "string" },
            content: { type: "string", description: "Message content" },
            type: {
              type: "string",
              enum: ["direct", "broadcast", "report", "assign"],
              description: "Message type. Default: direct",
            },
            recipientId: {
              type: "string",
              description: "Target agentId (required for direct/assign)",
            },
          },
          required: ["venueId", "content"],
          additionalProperties: false,
        },
        async execute(_id, params: any) {
          const inst = resolveInstance(params.agentId);
          if (!inst?.ready) return error(notReadyMsg(params.agentId));
          // v0.2.0: getConnection
          const handle = inst.maestro.getConnection ? inst.maestro.getConnection(params.venueId) : null;
          if (!handle && params.type !== "direct" && params.type != null) return error(`Agent "${inst.agentId}" is not a member of Venue ${params.venueId}`);

          const type = params.type ?? "direct";
          let msg: any;
          switch (type) {
            case "broadcast": msg = await handle.broadcast(params.content); break;
            case "report":    msg = await handle.reportTo(params.content); break;
            case "assign":
              if (!params.recipientId) return error("recipientId required for assign");
              msg = await handle.assignTo(params.recipientId, params.content); break;
            default: {
              if (!params.recipientId) return error("recipientId required for direct");
              if (handle) {
                msg = await handle.send(params.recipientId, params.content);
              } else {
                // No active connection — send directly via registry lookup
                let endpoint: string | null = null;
                if (inst.registryPath && existsSync(inst.registryPath)) {
                  try {
                    const reg = JSON.parse(readFileSync(inst.registryPath, 'utf8'));
                    const peer = reg.find((r: any) => r.agentId === params.recipientId);
                    endpoint = peer?.webhookEndpoint ?? null;
                  } catch { /* ignore */ }
                }
                if (!endpoint && inst.maestro.sendDirect) {
                  msg = await inst.maestro.sendDirect(params.recipientId, params.content);
                } else if (endpoint) {
                  // Raw HTTP POST directly to peer endpoint
                  const msgId = Math.random().toString(36).slice(2);
                  const body = JSON.stringify({
                    id: msgId, type: 'direct', content: params.content,
                    sender: { agentId: inst.agentId },
                    recipient: params.recipientId,
                    timestamp: Date.now(), version: '3.2',
                  });
                  const { request } = await import('http');
                  await new Promise<void>((resolve, reject) => {
                    const url = new URL(endpoint!);
                    const req = request({ hostname: url.hostname, port: url.port, path: url.pathname, method: 'POST', headers: { 'Content-Type': 'application/json' } }, (res) => resolve());
                    req.on('error', reject);
                    req.end(body);
                  });
                  msg = { id: msgId, type: 'direct', recipient: params.recipientId };
                } else {
                  return error(`No endpoint found for ${params.recipientId} and sendDirect not available`);
                }
              }
            }
          }
          return ok({ messageId: msg?.id, type: msg?.type, recipient: msg?.recipient, from: inst.agentId });
        },
      }
    );

    // --------------------------------------------------------
    // Tool: maestro_blackboard_set
    // --------------------------------------------------------
    api.registerTool(
      {
        name: "maestro_blackboard_set",
        label: "Blackboard Set",
        description: "Write a key-value entry to the shared Blackboard of a Venue.",
        parameters: {
          type: "object" as const,
          properties: {
            agentId: { type: "string", description: "Agent instance to use (optional)" },
            venueId: { type: "string" },
            key: { type: "string", description: "Blackboard key" },
            value: { description: "Any JSON-serialisable value" },
          },
          required: ["venueId", "key", "value"],
          additionalProperties: false,
        },
        async execute(_id, params: any) {
          const inst = resolveInstance(params.agentId);
          if (!inst?.ready) return error(notReadyMsg(params.agentId));
          const handle = inst.maestro.getConnection ? inst.maestro.getConnection(params.venueId) : null;
          if (!handle) return error(`Not a member of Venue ${params.venueId}`);
          // v0.2.0: bbSet instead of blackboard.set
          await handle.bbSet(params.key, params.value);
          return ok({ key: params.key, written: true, writtenBy: inst.agentId });
        },
      }
    );

    // --------------------------------------------------------
    // Tool: maestro_blackboard_get
    // --------------------------------------------------------
    api.registerTool(
      {
        name: "maestro_blackboard_get",
        label: "Blackboard Get",
        description: "Read a key or list all keys from the shared Blackboard of a Venue.",
        parameters: {
          type: "object" as const,
          properties: {
            agentId: { type: "string", description: "Agent instance to use (optional)" },
            venueId: { type: "string" },
            key: { type: "string", description: "Key to read. Omit to list all keys." },
            prefix: { type: "string", description: "Filter listed keys by prefix" },
          },
          required: ["venueId"],
          additionalProperties: false,
        },
        async execute(_id, params: any) {
          const inst = resolveInstance(params.agentId);
          if (!inst?.ready) return error(notReadyMsg(params.agentId));
          const handle = inst.maestro.getConnection ? inst.maestro.getConnection(params.venueId) : null;
          if (!handle) return error(`Not a member of Venue ${params.venueId}`);

          if (params.key) {
            // v0.2.0: bbGet returns value directly
            const value = await handle.bbGet(params.key);
            if (value === undefined || value === null) return ok({ key: params.key, value: null, found: false });
            return ok({ key: params.key, value, found: true });
          }
          // v0.2.0: no direct list on handle; use blackboard if available
          const bb = inst.maestro.getBlackboard ? inst.maestro.getBlackboard(params.venueId) : null;
          if (bb) {
            const keys = await bb.list(params.prefix);
            return ok({ keys, count: keys.length });
          }
          return ok({ keys: [], count: 0, note: 'List not available in this mode' });
        },
      }
    );

    // --------------------------------------------------------
    // Tool: maestro_venue_list
    // --------------------------------------------------------
    api.registerTool(
      {
        name: "maestro_venue_list",
        label: "List Maestro Venues",
        description: "List all Venues an agent is currently a member of.",
        parameters: {
          type: "object" as const,
          properties: {
            agentId: { type: "string", description: "Agent instance to query (optional)" },
          },
          additionalProperties: false,
        },
        async execute(_id, params: any) {
          const inst = resolveInstance(params.agentId);
          if (!inst?.ready) return error(notReadyMsg(params.agentId));
          // v0.2.0: listConnections
          const listFn = inst.maestro.listConnections ?? inst.maestro.listVenues;
          const venues = (listFn ? listFn.call(inst.maestro) : []).map((h: any) => {
            const info = h.getConnectionInfo ? h.getConnectionInfo() : (h.getVenueInfo ? h.getVenueInfo() : {});
            return {
              venueId: info.id,
              name: info.name,
              hostId: info.hostAgentId ?? info.hostId,
              status: info.status,
              membersCount: h.getMembers ? h.getMembers().length : 0,
            };
          });
          return ok({ agentId: inst.agentId, venues, count: venues.length });
        },
      }
    );

    // --------------------------------------------------------
    // Service: Concerto API server (port 3900)
    // Serves the human-facing observer API and SSE message feed
    // --------------------------------------------------------
    api.registerService({
      id: 'maestro-concerto-api',
      async start() {
        const { createServer, IncomingMessage, ServerResponse } = await import('http');
        const { readFileSync, existsSync } = await import('fs');
        const CONCERTO_PORT = 3900;
        const REG_PATH = 'C:\\Users\\there\\Projects\\Maestro\\maestro-protocol\\.maestro\\registry.json';

        const server = createServer((req: any, res: any) => {
          const url: string = req.url ?? '/';
          res.setHeader('Access-Control-Allow-Origin', '*');
          res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
          if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

          if (url === '/api/status' && req.method === 'GET') {
            const instances = [..._instances.entries()].map(([agentId, inst]) => ({
              agentId,
              ready: inst.ready,
              type: inst.type ?? 'openclaw',
              port: inst.webhookPort,
            }));
            const body = JSON.stringify({ ok: true, instances, ts: Date.now() });
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(body);
            return;
          }

          if (url === '/api/registry' && req.method === 'GET') {
            try {
              const peers = existsSync(REG_PATH) ? JSON.parse(readFileSync(REG_PATH, 'utf8')) : [];
              res.writeHead(200, { 'Content-Type': 'application/json' });
              res.end(JSON.stringify({ ok: true, peers }));
            } catch (e: any) {
              res.writeHead(500, { 'Content-Type': 'application/json' });
              res.end(JSON.stringify({ ok: false, error: e.message }));
            }
            return;
          }

          if (url === '/api/messages/history' && req.method === 'GET') {
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ ok: true, messages: _messageHistory.slice(-200) }));
            return;
          }

          if (url === '/api/messages/stream' && req.method === 'GET') {
            res.writeHead(200, {
              'Content-Type': 'text/event-stream',
              'Cache-Control': 'no-cache',
              'Connection': 'keep-alive',
            });
            // Send recent history on connect
            res.write(`data: ${JSON.stringify({ type: 'history', messages: _messageHistory.slice(-50) })}\n\n`);
            const listener: MessageEventListener = (event) => {
              try { res.write(`data: ${JSON.stringify({ type: 'message', event })}\n\n`); } catch { /* closed */ }
            };
            _messageListeners.add(listener);
            req.on('close', () => _messageListeners.delete(listener));
            return;
          }

          // Catch-all: serve Concerto UI for any unmatched request
          const uiPath = 'C:\\Users\\there\\Projects\\Maestro\\concerto\\index.html';
          try {
            const html = readFileSync(uiPath, 'utf8');
            res.writeHead(200, { 'Content-Type': 'text/html' });
            res.end(html);
          } catch (e: any) {
            res.writeHead(503, { 'Content-Type': 'text/plain' });
            res.end('Concerto UI not found: ' + (e as any).message);
          }
        });

        await new Promise<void>((resolve) => {
          server.listen(CONCERTO_PORT, '127.0.0.1', () => {
            api.logger.info(`Maestro Concerto API on http://127.0.0.1:${CONCERTO_PORT}`);
            resolve();
          });
          server.on('error', (err: Error) => {
            api.logger.warn(`Maestro Concerto API failed: ${err.message}`);
            resolve();
          });
        });
      },
      async stop() {
        _messageListeners.clear();
      },
    });

    api.logger.info(
      `Maestro plugin registered — ${agentConfigs.length} agent(s): ${agentConfigs.map(c => c.agentId).join(", ")}${
        hermesAgentConfigs.length > 0 ? ` + ${hermesAgentConfigs.length} Hermes agent(s): ${hermesAgentConfigs.map(c => c.agentId).join(", ")}` : ''
      }`
    );
  },
});

// ============================================================
// Helpers
// ============================================================

function notReadyMsg(agentId?: string): string {
  if (agentId) return `Maestro instance for agent "${agentId}" is not running or not configured.`;
  if (_instances.size === 0) return "No Maestro instances configured. Check plugin config.";
  return "No Maestro instances are ready. Check gateway logs.";
}

function ok(data: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }], details: {} };
}

function error(message: string) {
  return { content: [{ type: "text" as const, text: JSON.stringify({ error: message }) }], details: {}, isError: true };
}

