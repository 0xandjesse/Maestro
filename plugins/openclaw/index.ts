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

interface MaestroInstance {
  maestro: any;
  agentId: string;
  ready: boolean;
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
      // Legacy single-agent format
      agentId?: string;
      webhookPort?: number;
      blackboardPath?: string;
      discovery?: "mdns" | "file" | "none";
      registryPath?: string;
    };

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
      name: "Maestro webhook server",
      async start() {
        const { Maestro } = await import(
          "./node_modules/@maestro-protocol/core/dist/index.js"
        ) as any;

        for (const cfg of agentConfigs) {
          const { agentId, webhookPort = 3842, blackboardPath, discovery = "mdns", registryPath } = cfg;

          // Initialize slot immediately so tools can report "starting"
          _instances.set(agentId, { maestro: null, agentId, ready: false });

          try {
            const maestro = new Maestro({
              agentId,
              webhookPort,
              blackboardPath: blackboardPath || undefined,
              discovery:
                discovery === "none"
                  ? undefined
                  : {
                      method: discovery,
                      filePath: registryPath ?? `./.maestro/registry.json`,
                    },
            });
            await maestro.start();
            _instances.set(agentId, { maestro, agentId, ready: true });
            api.logger.info(`Maestro started — agentId=${agentId} port=${webhookPort}`);
          } catch (err) {
            api.logger.error(`Maestro failed to start for agent ${agentId}: ${err}`);
            _instances.set(agentId, { maestro: null, agentId, ready: false });
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
        description: "Show the status of all Maestro agent instances running in this gateway.",
        parameters: {
          type: "object" as const,
          properties: {},
          additionalProperties: false,
        },
        async execute(_id, _params) {
          const statuses = [..._instances.entries()].map(([agentId, inst]) => ({
            agentId,
            ready: inst.ready,
            webhookEndpoint: inst.maestro?.webhookEndpoint ?? null,
            peersDiscovered: inst.maestro?.peers?.length ?? 0,
          }));
          return ok({ instances: statuses, count: statuses.length });
        },
      },
      { optional: true }
    );

    // --------------------------------------------------------
    // Tool: maestro_peers
    // --------------------------------------------------------
    api.registerTool(
      {
        name: "maestro_peers",
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
          const peers = inst.maestro.peers;
          return ok({
            agentId: inst.agentId,
            peers: peers.map((p: any) => ({
              agentId: p.agentId,
              endpoint: p.webhookEndpoint,
              capabilities: p.capabilities ?? [],
              lastSeen: p.lastSeen,
            })),
            count: peers.length,
            selfEndpoint: inst.maestro.webhookEndpoint,
          });
        },
      },
      { optional: true }
    );

    // --------------------------------------------------------
    // Tool: maestro_venue_create
    // --------------------------------------------------------
    api.registerTool(
      {
        name: "maestro_venue_create",
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
            handle = inst.maestro.createHierarchicalVenue(params.name, params.roles, reportingChain);
          } else {
            handle = inst.maestro.createOpenVenue(params.name);
          }

          const info = handle.getVenueInfo();
          return ok({
            agentId: inst.agentId,
            venueId: info.id,
            name: info.name,
            hostId: info.hostId,
            entryMode: info.rules.entryMode,
            membersCount: handle.getMembers().length,
            webhookEndpoint: inst.maestro.webhookEndpoint,
          });
        },
      },
      { optional: true }
    );

    // --------------------------------------------------------
    // Tool: maestro_venue_join
    // --------------------------------------------------------
    api.registerTool(
      {
        name: "maestro_venue_join",
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

          // Same-process join: pass the host's VenueManager directly
          let hostManager: any = undefined;
          if (params.hostAgentId) {
            const hostInst = getInstance(params.hostAgentId);
            if (!hostInst?.ready) return error(`Host agent "${params.hostAgentId}" is not ready`);
            hostManager = hostInst.maestro.venueManager;
          }

          const response = inst.maestro.join(params.venueId, hostManager);
          if (response.status === "accepted") {
            return ok({ status: "accepted", agentId: inst.agentId, venueId: params.venueId, role: response.role });
          }
          return response.status === "pending"
            ? ok({ status: "pending", agentId: inst.agentId, venueId: params.venueId })
            : error(`Join rejected: ${response.reason ?? "unknown"}`);
        },
      },
      { optional: true }
    );

    // --------------------------------------------------------
    // Tool: maestro_send
    // --------------------------------------------------------
    api.registerTool(
      {
        name: "maestro_send",
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
          const handle = inst.maestro.getVenue(params.venueId);
          if (!handle) return error(`Agent "${inst.agentId}" is not a member of Venue ${params.venueId}`);

          const type = params.type ?? "direct";
          let msg: any;
          switch (type) {
            case "broadcast": msg = await handle.broadcast(params.content); break;
            case "report":    msg = await handle.reportTo(params.content); break;
            case "assign":
              if (!params.recipientId) return error("recipientId required for assign");
              msg = await handle.assignTo(params.recipientId, params.content); break;
            default:
              if (!params.recipientId) return error("recipientId required for direct");
              msg = await handle.send(params.recipientId, params.content);
          }
          return ok({ messageId: msg.id, type: msg.type, recipient: msg.recipient, from: inst.agentId });
        },
      },
      { optional: true }
    );

    // --------------------------------------------------------
    // Tool: maestro_blackboard_set
    // --------------------------------------------------------
    api.registerTool(
      {
        name: "maestro_blackboard_set",
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
          const handle = inst.maestro.getVenue(params.venueId);
          if (!handle) return error(`Not a member of Venue ${params.venueId}`);
          await handle.blackboard.set(params.key, params.value, inst.agentId);
          return ok({ key: params.key, written: true, writtenBy: inst.agentId });
        },
      },
      { optional: true }
    );

    // --------------------------------------------------------
    // Tool: maestro_blackboard_get
    // --------------------------------------------------------
    api.registerTool(
      {
        name: "maestro_blackboard_get",
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
          const handle = inst.maestro.getVenue(params.venueId);
          if (!handle) return error(`Not a member of Venue ${params.venueId}`);

          if (params.key) {
            const entry = await handle.blackboard.getEntry(params.key);
            if (!entry) return ok({ key: params.key, value: null, found: false });
            return ok({ key: entry.key, value: entry.value, writtenBy: entry.writtenBy, version: entry.version, found: true });
          }
          const keys = await handle.blackboard.list(params.prefix);
          return ok({ keys, count: keys.length });
        },
      },
      { optional: true }
    );

    // --------------------------------------------------------
    // Tool: maestro_venue_list
    // --------------------------------------------------------
    api.registerTool(
      {
        name: "maestro_venue_list",
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
          const venues = inst.maestro.listVenues().map((h: any) => {
            const info = h.getVenueInfo();
            return {
              venueId: info.id,
              name: info.name,
              hostId: info.hostId,
              status: info.status,
              membersCount: h.getMembers().length,
            };
          });
          return ok({ agentId: inst.agentId, venues, count: venues.length });
        },
      },
      { optional: true }
    );

    api.logger.info(
      `Maestro plugin registered — ${agentConfigs.length} agent(s): ${agentConfigs.map(c => c.agentId).join(", ")}`
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
  return { content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }] };
}

function error(message: string) {
  return { content: [{ type: "text" as const, text: JSON.stringify({ error: message }) }], isError: true };
}
