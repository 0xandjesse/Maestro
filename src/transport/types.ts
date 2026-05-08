// ============================================================
// Maestro Protocol — Transport Types
// ============================================================

import { MaestroMessage } from '../types/index.js';

// ----------------------------------------------------------
// Message types (extends base MaestroMessage.type)
// ----------------------------------------------------------

export type TransportMessageType =
  | 'direct'
  | 'broadcast'
  | 'report'        // Worker → supervisor
  | 'assign'        // Supervisor → worker
  | 'connection:invitation'
  | 'connection:announcement'
  | 'blackboard:update';

// ----------------------------------------------------------
// Outbound message options
// ----------------------------------------------------------

export interface SendOptions {
  priority?: 'low' | 'normal' | 'high' | 'urgent';
  replyTo?: string;
  payload?: Record<string, unknown>;
  artifacts?: Artifact[];
}

export interface Artifact {
  type: 'file' | 'link' | 'code' | 'image' | 'json';
  name: string;
  url?: string;
  content?: string;
  mimeType?: string;
}

// ----------------------------------------------------------
// Webhook event
// ----------------------------------------------------------

export interface WebhookEvent {
  eventId: string;
  timestamp: number;
  stageId: string;
  type:
    | 'message'
    | 'member:joined'
    | 'member:left'
    | 'role:changed'
    | 'blackboard:updated'
    | 'venue:closed'
    | 'connection:invitation';
  payload: Record<string, unknown>;
  /** Signed by Connection host for verification */
  signature: string;
}

// ----------------------------------------------------------
// Discovery
// ----------------------------------------------------------

export type DiscoveryMethod = 'mdns' | 'file' | 'redis' | 'none';

export interface DiscoveryConfig {
  method: DiscoveryMethod;
  filePath?: string;    // For 'file' method
  redisUrl?: string;    // For 'redis' method
}

// ----------------------------------------------------------
// Agent registration (for discovery)
// ----------------------------------------------------------

export interface AgentRegistration {
  agentId: string;
  webhookEndpoint: string;
  publicKey?: string;
  wallet?: string;
  capabilities?: string[];
  registeredAt: number;
  lastSeen: number;
}

// ----------------------------------------------------------
// Maestro SDK config
// ----------------------------------------------------------

export interface MaestroConfig {
  agentId: string;
  wallet?: string;
  webhookPort?: number;
  webhookPath?: string;
  discovery?: DiscoveryConfig;
  publicKey?: string;
  privateKey?: string;
  /** HTTP transport config. When present, boots an HttpTransport server. */
  transport?: {
    port?: number;
    registryPath?: string;
    /** Path to the SQLite blackboard DB. Default: .maestro/blackboard.db */
    dbPath?: string;
  };
  /** OpenClaw integration. When present, wakes agent sessions on inbound messages. */
  openclaw?: {
    gatewayUrl: string;
    hookToken: string;
    agentSessions?: Record<string, string>;
  };
  /** Hermes Agent integration. When present, wakes Hermes agent sessions on inbound messages. */
  hermes?: {
    /** Base URL of the Hermes API server, e.g. http://192.168.56.101:8642 */
    apiUrl: string;
    /** Bearer token (API_SERVER_KEY in Hermes .env) */
    apiKey: string;
    /** Map of Maestro agentId → Hermes conversation name */
    agentSessions?: Record<string, string>;
    /** If true, awaits run completion before returning. Default: false */
    awaitResponse?: boolean;
    /** Timeout ms for awaited responses. Default: 30000 */
    responseTimeoutMs?: number;
    /**
     * Agent IDs that are humans (not routable Maestro peers).
     * When Hermes replies to one of these, onHumanReply is called
     * instead of waking an OpenClaw agent session.
     */
    humanAgentIds?: string[];
    /**
     * Called when Hermes completes a reply to a human (non-routable) agent.
     * Use this to surface the reply in a UI (e.g. Concerto feed).
     */
    onHumanReply?: (fromAgentId: string, toAgentId: string, content: string) => void;
  };
}

// ----------------------------------------------------------
// Message handler
// ----------------------------------------------------------

export type MessageHandler = (message: MaestroMessage) => void | Promise<void>;
export type EventHandler<T = Record<string, unknown>> = (event: T) => void | Promise<void>;
