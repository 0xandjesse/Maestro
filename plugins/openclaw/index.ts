// ============================================================
// Maestro Protocol — OpenClaw Plugin
// ============================================================
//
// Gives OpenClaw agents Maestro presence: they can discover
// other agents, create/join Venues, share Blackboards, and
// send structured messages across process boundaries.
//
// Install:
//   openclaw plugins install @maestro-protocol/openclaw-plugin
//
// Config (in openclaw.json):
//   plugins.entries.maestro-protocol.config:
//     agentId: "songbird"        # defaults to agent name
//     webhookPort: 3842          # Maestro webhook port
//     discovery: "mdns"          # mdns | file | none
//     blackboardPath: "./.maestro/bb.db"  # optional persistence
// ============================================================

import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { createPluginRuntimeStore } from "openclaw/plugin-sdk/runtime-store";
import { Type } from "@sinclair/typebox";

// Lazy-load Maestro so the plugin doesn't hard-fail if the package
// isn't installed yet (the tool check_fn handles that gracefully).
async function getMaestro() {
  const { Maestro } = await import("@maestro-protocol/core");
  return Maestro;
}

// ============================================================
// Runtime state — one Maestro instance per plugin lifetime
// ============================================================

const store = createPluginRuntimeStore<{
  maestro: InstanceType<Awaited<ReturnType<typeof getMaestro>>> | null;
  ready: boolean;
}>();

store.set({ maestro: null, ready: false });

// ============================================================
// Plugin entry
// ============================================================

export default definePluginEntry({
  id: "maestro-protocol",
  name: "Maestro Protocol",
  description: "Open agent coordination — Venues, Blackboards, and multi-agent messaging",

  async register(api) {
    const config = api.pluginConfig as {
      agentId?: string;
      webhookPort?: number;
      blackboardPath?: string;
      discovery?: "mdns" | "file" | "none";
      registryPath?: string;
    };

    // Resolve agentId from plugin config or fall back to the OpenClaw agent name
    const agentId =
      config.agentId ??
      (api.config as { agent?: { name?: string } }).agent?.name ??
      "openclaw-agent";

    const webhookPort = config.webhookPort ?? 3842;
    const discoveryMethod = config.discovery ?? "mdns";

    // --------------------------------------------------------
    // Background service: start the Maestro webhook server
    // --------------------------------------------------------
    api.registerService({
      id: "maestro-webhook",
      name: "Maestro webhook server",
      async start() {
        try {
          const MaestroClass = await getMaestro();
          const maestro = new MaestroClass({
            agentId,
            webhookPort,
            blackboardPath: config.blackboardPath,
            discovery:
              discoveryMethod === "none"
                ? undefined
                : {
                    method: discoveryMethod,
                    filePath: config.registryPath ?? `./.maestro/registry.json`,
                  },
          });

          await maestro.start();
          store.set({ maestro, ready: true });
          api.logger.info(`Maestro started — agentId=${agentId} port=${webhookPort}`);
        } catch (err) {
          api.logger.error(`Maestro failed to start: ${err}`);
          store.set({ maestro: null, ready: false });
        }
      },
      async stop() {
        const { maestro } = store.get();
        if (maestro) {
          await maestro.stop();
          store.set({ maestro: null, ready: false });
          api.logger.info("Maestro stopped");
        }
      },
    });

    // --------------------------------------------------------
    // Tool: maestro_venue_create
    // --------------------------------------------------------
    api.registerTool(
      {
        name: "maestro_venue_create",
        description:
          "Create a Maestro Venue — a structured space for multi-agent coordination with optional hierarchy and a shared Blackboard.",
        parameters: Type.Object({
          name: Type.String({ description: "Human-readable Venue name" }),
          entryMode: Type.Optional(
            Type.Union(
              [
                Type.Literal("open"),
                Type.Literal("invitation"),
                Type.Literal("assignment"),
              ],
              { description: "Who can join. Default: open" }
            )
          ),
          roles: Type.Optional(
            Type.Array(Type.String(), {
              description:
                'Hierarchy roles from highest to lowest, e.g. ["lead","worker"]. Omit for flat peer Venue.',
            })
          ),
        }),
        async execute(_id, params) {
          const { maestro } = store.get();
          if (!maestro) {
            return error("Maestro is not running. Check plugin config.");
          }

          let handle;
          if (params.roles && params.roles.length >= 2) {
            const reportingChain: Record<string, string> = {};
            for (let i = 1; i < params.roles.length; i++) {
              reportingChain[params.roles[i]] = params.roles[i - 1];
            }
            handle = maestro.createHierarchicalVenue(
              params.name,
              params.roles,
              reportingChain
            );
          } else {
            handle = maestro.createOpenVenue(params.name);
          }

          const info = handle.getVenueInfo();
          return ok({
            venueId: info.id,
            name: info.name,
            hostId: info.hostId,
            entryMode: info.rules.entryMode,
            hierarchy: info.rules.hierarchy ?? null,
            membersCount: handle.getMembers().length,
            webhookEndpoint: maestro.webhookEndpoint,
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
        description:
          "Join an existing Maestro Venue by ID. Use when another agent has invited you or shared a Venue ID.",
        parameters: Type.Object({
          venueId: Type.String({ description: "ID of the Venue to join" }),
          hostEndpoint: Type.Optional(
            Type.String({
              description:
                "Webhook endpoint of the Venue host (required for remote/cross-process join)",
            })
          ),
        }),
        async execute(_id, params) {
          const { maestro } = store.get();
          if (!maestro) return error("Maestro is not running.");

          // Local join (same process) — pass no hostManager for network mode
          const response = maestro.join(params.venueId);

          if (response.status === "accepted") {
            return ok({
              status: "accepted",
              venueId: params.venueId,
              role: response.role,
              supervisorId: response.supervisorId ?? null,
            });
          } else if (response.status === "pending") {
            return ok({ status: "pending", venueId: params.venueId });
          } else {
            return error(`Join rejected: ${response.reason ?? "unknown"}`);
          }
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
          "Send a Maestro message to an agent in a Venue. Supports direct messages, broadcasts, reports (to supervisor), and assignments (to subordinate).",
        parameters: Type.Object({
          venueId: Type.String({ description: "Venue to send within" }),
          content: Type.String({ description: "Message content" }),
          type: Type.Optional(
            Type.Union(
              [
                Type.Literal("direct"),
                Type.Literal("broadcast"),
                Type.Literal("report"),
                Type.Literal("assign"),
              ],
              { description: "Message type. Default: direct" }
            )
          ),
          recipientId: Type.Optional(
            Type.String({
              description:
                "Target agentId (required for direct/assign, omit for broadcast/report)",
            })
          ),
        }),
        async execute(_id, params) {
          const { maestro } = store.get();
          if (!maestro) return error("Maestro is not running.");

          const handle = maestro.getVenue(params.venueId);
          if (!handle) {
            return error(`Not a member of Venue ${params.venueId}`);
          }

          const type = params.type ?? "direct";
          let msg;

          switch (type) {
            case "broadcast":
              msg = await handle.broadcast(params.content);
              break;
            case "report":
              msg = await handle.reportTo(params.content);
              break;
            case "assign":
              if (!params.recipientId) {
                return error("recipientId is required for assign messages");
              }
              msg = await handle.assignTo(params.recipientId, params.content);
              break;
            default:
              if (!params.recipientId) {
                return error("recipientId is required for direct messages");
              }
              msg = await handle.send(params.recipientId, params.content);
          }

          return ok({ messageId: msg.id, type: msg.type, recipient: msg.recipient });
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
        description:
          "Write a key-value entry to the shared Blackboard of a Venue. All Venue members can read it. Last-write-wins.",
        parameters: Type.Object({
          venueId: Type.String(),
          key: Type.String({ description: "Blackboard key (supports namespacing with ':')" }),
          value: Type.Unknown({ description: "Any JSON-serialisable value" }),
        }),
        async execute(_id, params) {
          const { maestro } = store.get();
          if (!maestro) return error("Maestro is not running.");

          const handle = maestro.getVenue(params.venueId);
          if (!handle) return error(`Not a member of Venue ${params.venueId}`);

          await handle.blackboard.set(params.key, params.value, agentId);
          return ok({ key: params.key, written: true });
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
        description:
          "Read a key or list all keys from the shared Blackboard of a Venue.",
        parameters: Type.Object({
          venueId: Type.String(),
          key: Type.Optional(
            Type.String({ description: "Key to read. Omit to list all keys." })
          ),
          prefix: Type.Optional(
            Type.String({ description: "Filter listed keys by prefix" })
          ),
        }),
        async execute(_id, params) {
          const { maestro } = store.get();
          if (!maestro) return error("Maestro is not running.");

          const handle = maestro.getVenue(params.venueId);
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
        description: "List all Venues this agent is currently a member of.",
        parameters: Type.Object({}),
        async execute(_id, _params) {
          const { maestro } = store.get();
          if (!maestro) return error("Maestro is not running.");

          const venues = maestro.listVenues().map((h) => {
            const info = h.getVenueInfo();
            return {
              venueId: info.id,
              name: info.name,
              hostId: info.hostId,
              status: info.status,
              membersCount: h.getMembers().length,
            };
          });

          return ok({ venues, count: venues.length });
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
          "List Maestro agents discovered on the local network (mDNS) or file registry. Use this to find other agents to coordinate with.",
        parameters: Type.Object({}),
        async execute(_id, _params) {
          const { maestro } = store.get();
          if (!maestro) return error("Maestro is not running.");

          const peers = maestro.peers;
          return ok({
            peers: peers.map((p) => ({
              agentId: p.agentId,
              endpoint: p.webhookEndpoint,
              capabilities: p.capabilities ?? [],
              lastSeen: p.lastSeen,
            })),
            count: peers.length,
            selfEndpoint: maestro.webhookEndpoint,
          });
        },
      },
      { optional: true }
    );

    api.logger.info(`Maestro plugin registered — agentId=${agentId}`);
  },
});

// ============================================================
// Helpers
// ============================================================

function ok(data: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }],
  };
}

function error(message: string) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify({ error: message }) }],
    isError: true,
  };
}
