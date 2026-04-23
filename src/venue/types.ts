// ============================================================
// Maestro Protocol — Venue Types
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
// Venue Rules
// ----------------------------------------------------------

export type EntryMode = 'open' | 'invitation' | 'approval' | 'assignment';
export type MemberVisibility = 'all' | 'role-based' | 'hierarchy';

export interface VenueHierarchy {
  roles: string[];
  /** e.g. { worker: 'lead', cmo: 'coo' } */
  reportingChain: Record<string, string>;
  defaultRole: string;
}

export interface VenueRules {
  entryMode: EntryMode;
  maxMembers?: number;
  memberVisibility: MemberVisibility;
  hierarchy?: VenueHierarchy;
  /** Permission map: role → list of allowed permissions */
  permissions: Record<string, Permission[]>;
  /** Optional provenance requirements for messages in this Venue */
  provenancePolicy?: ProvenancePolicy;
}

// ----------------------------------------------------------
// Members
// ----------------------------------------------------------

export interface VenueMember {
  agentId: string;
  role: string;
  joinedAt: number;
  supervisorId?: string;
  subordinateIds?: string[];
  capabilities?: string[];
}

// ----------------------------------------------------------
// Venue Status
// ----------------------------------------------------------

export type VenueStatus = 'created' | 'active' | 'closed';

// ----------------------------------------------------------
// Venue
// ----------------------------------------------------------

export interface Venue {
  id: string;
  name: string;
  hostId: string;
  rules: VenueRules;
  members: VenueMember[];
  createdAt: number;
  expiresAt?: number;
  status: VenueStatus;
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
  venueId?: string;
  role?: string;
  supervisorId?: string;
  blackboard?: {
    httpEndpoint: string;
    websocket?: string;
  };
  members?: VenueMember[];
  rules?: VenueRules;
  requestId?: string;  // For pending status
  reason?: string;     // For rejected status
}

// ----------------------------------------------------------
// Venue Creation
// ----------------------------------------------------------

export interface CreateVenueRequest {
  name: string;
  rules: VenueRules;
  initialMembers?: Array<{
    agentId: string;
    role: string;
    capabilities?: string[];
  }>;
  expiresAt?: number;
}

export interface CreateVenueResponse {
  venueId: string;
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
// Venue Events
// ----------------------------------------------------------

export type VenueEventType =
  | 'message'
  | 'member:joined'
  | 'member:left'
  | 'role:changed'
  | 'blackboard:updated'
  | 'venue:closed'
  | 'venue:invitation';

export interface VenueEvent {
  eventId: string;
  timestamp: number;
  venueId: string;
  type: VenueEventType;
  payload: Record<string, unknown>;
  /** Signed by Venue host for verification */
  signature: string;
}

// ----------------------------------------------------------
// Permission Check Result
// ----------------------------------------------------------

export interface PermissionCheckResult {
  allowed: boolean;
  reason?: string;
}
