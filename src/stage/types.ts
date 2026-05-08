// ============================================================
// Maestro Protocol — Stage Types
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
  | 'stage:close'
  | 'stage:transfer';

// ----------------------------------------------------------
// Stage Rules
// ----------------------------------------------------------

export type EntryMode = 'open' | 'invitation' | 'approval' | 'assignment';
export type MemberVisibility = 'all' | 'role-based' | 'hierarchy';

export interface StageHierarchy {
  roles: string[];
  /** e.g. { worker: 'lead', cmo: 'coo' } */
  reportingChain: Record<string, string>;
  defaultRole: string;
}

export interface StageRules {
  entryMode: EntryMode;
  maxMembers?: number;
  memberVisibility: MemberVisibility;
  hierarchy?: StageHierarchy;
  /** Permission map: role → list of allowed permissions */
  permissions: Record<string, Permission[]>;
  /** Optional provenance requirements for messages in this Stage */
  provenancePolicy?: ProvenancePolicy;
}

// ----------------------------------------------------------
// Members
// ----------------------------------------------------------

export interface StageMember {
  agentId: string;
  role: string;
  joinedAt: number;
  supervisorId?: string;
  subordinateIds?: string[];
  capabilities?: string[];
}

// ----------------------------------------------------------
// Stage Status
// ----------------------------------------------------------

export type StageStatus = 'created' | 'active' | 'closed';

// ----------------------------------------------------------
// Stage
// ----------------------------------------------------------

export interface Stage {
  id: string;
  name: string;
  hostId: string;
  rules: StageRules;
  members: StageMember[];
  createdAt: number;
  expiresAt?: number;
  status: StageStatus;
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
  stageId?: string;
  role?: string;
  supervisorId?: string;
  blackboard?: {
    httpEndpoint: string;
    websocket?: string;
  };
  members?: StageMember[];
  rules?: StageRules;
  requestId?: string;  // For pending status
  reason?: string;     // For rejected status
}

// ----------------------------------------------------------
// Stage Creation
// ----------------------------------------------------------

export interface CreateStageRequest {
  name: string;
  rules: StageRules;
  initialMembers?: Array<{
    agentId: string;
    role: string;
    capabilities?: string[];
  }>;
  expiresAt?: number;
}

export interface CreateStageResponse {
  stageId: string;
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
// Stage Events
// ----------------------------------------------------------

export type StageEventType =
  | 'message'
  | 'member:joined'
  | 'member:left'
  | 'role:changed'
  | 'blackboard:updated'
  | 'stage:closed'
  | 'stage:invitation';

export interface StageEvent {
  eventId: string;
  timestamp: number;
  stageId: string;
  type: StageEventType;
  payload: Record<string, unknown>;
  /** Signed by Stage host for verification */
  signature: string;
}

// ----------------------------------------------------------
// Permission Check Result
// ----------------------------------------------------------

export interface PermissionCheckResult {
  allowed: boolean;
  reason?: string;
}
