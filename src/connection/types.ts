// ============================================================
// Maestro Protocol - Connection Types
// ============================================================

import { ProvenancePolicy } from '../types/index.js';

// ----------------------------------------------------------
// Permissions
// ----------------------------------------------------------

export type Permission =
  | 'message:send'
  | 'message:broadcast'
  | 'blackboard:read'
  | 'blackboard:write'
  | 'member:invite'
  | 'member:remove'
  | 'role:assign'
  | 'venue:close'
  | 'venue:transfer';

// ----------------------------------------------------------
// Connection Rules
// ----------------------------------------------------------

export type EntryMode = 'open' | 'invitation' | 'approval' | 'assignment';
export type MemberVisibility = 'all' | 'role-based' | 'hierarchy';

export interface ConnectionHierarchy {
  roles: string[];
  /** e.g. { worker: 'lead', cmo: 'coo' } */
  reportingChain: Record<string, string>;
  defaultRole: string;
}

export interface ConnectionRules {
  entryMode: EntryMode;
  maxMembers?: number;
  memberVisibility: MemberVisibility;
  hierarchy?: ConnectionHierarchy;
  /** Permission map: role  list of allowed permissions */
  permissions: Record<string, Permission[]>;
  /** Optional provenance requirements for messages in this Connection */
  provenancePolicy?: ProvenancePolicy;
}

// ----------------------------------------------------------
// Members
// ----------------------------------------------------------

export interface ConnectionMember {
  agentId: string;
  role: string;
  joinedAt: number;
  supervisorId?: string;
  subordinateIds?: string[];
  capabilities?: string[];
}

// ----------------------------------------------------------
// Connection Status
// ----------------------------------------------------------

export type ConnectionStatus = 'created' | 'active' | 'closed';

// ----------------------------------------------------------
// Connection
// ----------------------------------------------------------

export interface Connection {
  id: string;
  name: string;
  hostId: string;
  rules: ConnectionRules;
  members: ConnectionMember[];
  createdAt: number;
  expiresAt?: number;
  status: ConnectionStatus;
}

// ----------------------------------------------------------
// Join Request / Response
// ----------------------------------------------------------

export interface JoinRequest {
  protocolVersion: string;
  agentId: string;
  identity: {
    wallet?: string;
    publicKey?: string;
  };
  capabilities?: string[];
  webhookEndpoint: string;
  inviteToken?: string;
}

export type JoinStatus = 'accepted' | 'pending' | 'rejected';

export interface JoinResponse {
  status: JoinStatus;
  connectionId?: string;
  /** Display name of the Connection (returned on accepted, for local mirroring) */
  name?: string;
  /** agentId of the Connection host (returned on accepted, for local mirroring) */
  hostAgentId?: string;
  role?: string;
  supervisorId?: string;
  blackboard?: {
    httpEndpoint: string;
    websocket?: string;
  };
  members?: ConnectionMember[];
  rules?: ConnectionRules;
  requestId?: string;  // For pending status
  reason?: string;     // For rejected status
}

// ----------------------------------------------------------
// Connection Creation
// ----------------------------------------------------------

export interface CreateConnectionRequest {
  name: string;
  rules: ConnectionRules;
  initialMembers?: Array<{
    agentId: string;
    role: string;
    capabilities?: string[];
  }>;
  expiresAt?: number;
}

export interface CreateConnectionResponse {
  connectionId: string;
  joinEndpoint: string;
}

// ----------------------------------------------------------
// Role Transfer
// ----------------------------------------------------------

export interface RoleTransferRequest {
  role: string;
  to: string;
  reason?: string;
}

// ----------------------------------------------------------
// Connection Events
// ----------------------------------------------------------

export type ConnectionEventType =
  | 'message'
  | 'member:joined'
  | 'member:left'
  | 'role:changed'
  | 'blackboard:updated'
  | 'venue:closed'
  | 'venue:invitation';

export interface ConnectionEvent {
  eventId: string;
  timestamp: number;
  connectionId: string;
  type: ConnectionEventType;
  payload: Record<string, unknown>;
  /** Signed by Connection host for verification */
  signature: string;
}

// ----------------------------------------------------------
// Permission Check Result
// ----------------------------------------------------------

export interface PermissionCheckResult {
  allowed: boolean;
  reason?: string;
}
