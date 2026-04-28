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
}

// ----------------------------------------------------------
// Message handler
// ----------------------------------------------------------

export type MessageHandler = (message: MaestroMessage) => void | Promise<void>;
export type EventHandler<T = Record<string, unknown>> = (event: T) => void | Promise<void>;
