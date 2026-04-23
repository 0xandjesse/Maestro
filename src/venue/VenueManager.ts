// ============================================================
// Maestro Protocol — Venue Manager
// ============================================================
//
// Manages Venue lifecycle: creation, member management,
// permission enforcement, role assignment, and closure.
//
// This is an in-process implementation suitable for local mode
// and testing. Network mode venues delegate to a platform
// host (e.g. TaskMaster API).
// ============================================================

import { randomUUID } from 'crypto';
import {
  CreateVenueRequest,
  JoinRequest,
  JoinResponse,
  Permission,
  PermissionCheckResult,
  RoleTransferRequest,
  Venue,
  VenueMember,
  VenueRules,
  VenueStatus,
} from './types.js';

// ----------------------------------------------------------
// Default permission sets
// ----------------------------------------------------------

export const DEFAULT_PERMISSIONS: Record<string, Permission[]> = {
  lead: [
    'message:send',
    'message:broadcast',
    'blackboard:read',
    'blackboard:write',
    'member:invite',
    'member:remove',
    'role:assign',
    'venue:close',
    'venue:transfer',
  ],
  worker: [
    'message:send',
    'blackboard:read',
    'blackboard:write',
  ],
  observer: [
    'blackboard:read',
  ],
};

// ----------------------------------------------------------
// VenueManager
// ----------------------------------------------------------

export class VenueManager {
  private venues = new Map<string, Venue>();

  // ----------------------------------------------------------
  // Create
  // ----------------------------------------------------------

  create(request: CreateVenueRequest, hostId: string): Venue {
    const id = randomUUID();
    const now = Date.now();

    const members: VenueMember[] = [];

    // Host is always the first member with lead role (or the hierarchy's top role)
    const hostRole = request.rules.hierarchy?.roles[0] ?? 'lead';
    members.push({
      agentId: hostId,
      role: hostRole,
      joinedAt: now,
      subordinateIds: [],
    });

    // Add initial members
    if (request.initialMembers) {
      for (const im of request.initialMembers) {
        if (im.agentId === hostId) continue; // already added
        members.push({
          agentId: im.agentId,
          role: im.role,
          joinedAt: now,
          capabilities: im.capabilities,
          subordinateIds: [],
        });
      }
    }

    // Wire up hierarchy if defined
    if (request.rules.hierarchy) {
      this.wireHierarchy(members, request.rules.hierarchy.reportingChain);
    }

    const venue: Venue = {
      id,
      name: request.name,
      hostId,
      rules: request.rules,
      members,
      createdAt: now,
      status: members.length > 1 ? 'active' : 'created',
      ...(request.expiresAt ? { expiresAt: request.expiresAt } : {}),
    };

    this.venues.set(id, venue);
    return venue;
  }

  // ----------------------------------------------------------
  // Join
  // ----------------------------------------------------------

  processJoin(venueId: string, request: JoinRequest): JoinResponse {
    const venue = this.venues.get(venueId);
    if (!venue) {
      return { status: 'rejected', reason: 'venue_not_found' };
    }

    if (venue.status === 'closed') {
      return { status: 'rejected', reason: 'venue_closed' };
    }

    const rules = venue.rules;

    // Check entry mode
    if (rules.entryMode === 'approval') {
      // In a real implementation this would create a pending request
      return { status: 'pending', requestId: randomUUID() };
    }

    if (rules.entryMode === 'invitation' || rules.entryMode === 'assignment') {
      if (!request.inviteToken) {
        return { status: 'rejected', reason: 'invite_required' };
      }
      // Invite token validation would happen here in network mode
    }

    // Check capacity
    if (rules.maxMembers && venue.members.length >= rules.maxMembers) {
      return { status: 'rejected', reason: 'venue_full' };
    }

    // Already a member?
    if (venue.members.find(m => m.agentId === request.agentId)) {
      return { status: 'rejected', reason: 'already_member' };
    }

    // Add member with default role
    const defaultRole = rules.hierarchy?.defaultRole ?? 'worker';
    const member: VenueMember = {
      agentId: request.agentId,
      role: defaultRole,
      joinedAt: Date.now(),
      capabilities: request.capabilities,
      subordinateIds: [],
    };

    venue.members.push(member);
    venue.status = 'active';

    // Wire up hierarchy for new member
    if (rules.hierarchy) {
      this.wireHierarchy(venue.members, rules.hierarchy.reportingChain);
    }

    const supervisor = this.getSupervisor(venue, request.agentId);

    return {
      status: 'accepted',
      venueId: venue.id,
      role: defaultRole,
      supervisorId: supervisor?.agentId,
      members: this.visibleMembers(venue, request.agentId),
      rules: venue.rules,
    };
  }

  // ----------------------------------------------------------
  // Permission Checks
  // ----------------------------------------------------------

  checkPermission(
    venueId: string,
    agentId: string,
    permission: Permission,
  ): PermissionCheckResult {
    const venue = this.venues.get(venueId);
    if (!venue) return { allowed: false, reason: 'venue_not_found' };
    if (venue.status === 'closed') return { allowed: false, reason: 'venue_closed' };

    const member = venue.members.find(m => m.agentId === agentId);
    if (!member) return { allowed: false, reason: 'not_a_member' };

    const rolePermissions = venue.rules.permissions[member.role] ?? [];
    if (rolePermissions.includes(permission)) {
      return { allowed: true };
    }

    return {
      allowed: false,
      reason: `role '${member.role}' lacks permission '${permission}'`,
    };
  }

  requirePermission(venueId: string, agentId: string, permission: Permission): void {
    const result = this.checkPermission(venueId, agentId, permission);
    if (!result.allowed) {
      throw new Error(`Permission denied: ${result.reason}`);
    }
  }

  // ----------------------------------------------------------
  // Role Management
  // ----------------------------------------------------------

  assignRole(
    venueId: string,
    requestingAgentId: string,
    targetAgentId: string,
    newRole: string,
  ): void {
    this.requirePermission(venueId, requestingAgentId, 'role:assign');

    const venue = this.getVenueOrThrow(venueId);

    const validRoles = venue.rules.hierarchy?.roles ?? Object.keys(venue.rules.permissions);
    if (!validRoles.includes(newRole)) {
      throw new Error(`Unknown role: ${newRole}`);
    }

    const member = venue.members.find(m => m.agentId === targetAgentId);
    if (!member) throw new Error(`Agent ${targetAgentId} is not a member of venue ${venueId}`);

    member.role = newRole;

    // Re-wire hierarchy after role change
    if (venue.rules.hierarchy) {
      this.wireHierarchy(venue.members, venue.rules.hierarchy.reportingChain);
    }
  }

  transferRole(
    venueId: string,
    requestingAgentId: string,
    request: RoleTransferRequest,
  ): void {
    this.requirePermission(venueId, requestingAgentId, 'venue:transfer');
    const venue = this.getVenueOrThrow(venueId);

    const requester = venue.members.find(m => m.agentId === requestingAgentId);
    const target = venue.members.find(m => m.agentId === request.to);

    if (!requester) throw new Error('Requester not found');
    if (!target) throw new Error(`Transfer target ${request.to} is not a member`);

    const prevRole = requester.role;
    const defaultRole = venue.rules.hierarchy?.defaultRole ?? 'worker';

    // Swap roles
    requester.role = defaultRole;
    target.role = request.role;

    // Update host if lead transferred
    if (prevRole === venue.rules.hierarchy?.roles[0]) {
      venue.hostId = request.to;
    }

    if (venue.rules.hierarchy) {
      this.wireHierarchy(venue.members, venue.rules.hierarchy.reportingChain);
    }
  }

  // ----------------------------------------------------------
  // Member Management
  // ----------------------------------------------------------

  removeMember(venueId: string, requestingAgentId: string, targetAgentId: string): void {
    this.requirePermission(venueId, requestingAgentId, 'member:remove');
    const venue = this.getVenueOrThrow(venueId);

    if (targetAgentId === venue.hostId) {
      throw new Error('Cannot remove the Venue host. Transfer ownership first.');
    }

    venue.members = venue.members.filter(m => m.agentId !== targetAgentId);

    if (venue.rules.hierarchy) {
      this.wireHierarchy(venue.members, venue.rules.hierarchy.reportingChain);
    }
  }

  leave(venueId: string, agentId: string): void {
    const venue = this.getVenueOrThrow(venueId);
    if (agentId === venue.hostId) {
      throw new Error('Host cannot leave. Close or transfer the Venue first.');
    }
    venue.members = venue.members.filter(m => m.agentId !== agentId);
  }

  // ----------------------------------------------------------
  // Visibility
  // ----------------------------------------------------------

  /**
   * Returns the list of members visible to a given agent,
   * respecting the Venue's memberVisibility setting.
   */
  visibleMembers(venue: Venue, agentId: string): VenueMember[] {
    switch (venue.rules.memberVisibility) {
      case 'all':
        return [...venue.members];

      case 'hierarchy': {
        const member = venue.members.find(m => m.agentId === agentId);
        if (!member) return [];
        // Can see: own supervisor + own subordinates + peers under same supervisor
        const supervisorId = member.supervisorId;
        return venue.members.filter(m => {
          if (m.agentId === agentId) return true;
          if (m.agentId === supervisorId) return true;
          if (member.subordinateIds?.includes(m.agentId)) return true;
          // Peers: same supervisor
          if (supervisorId && m.supervisorId === supervisorId) return true;
          return false;
        });
      }

      case 'role-based': {
        const member = venue.members.find(m => m.agentId === agentId);
        if (!member) return [];
        // Same role can see each other + supervisors
        return venue.members.filter(m => {
          if (m.agentId === agentId) return true;
          if (m.role === member.role) return true;
          if (m.agentId === member.supervisorId) return true;
          return false;
        });
      }
    }
  }

  // ----------------------------------------------------------
  // Lifecycle
  // ----------------------------------------------------------

  close(venueId: string, requestingAgentId: string): void {
    this.requirePermission(venueId, requestingAgentId, 'venue:close');
    const venue = this.getVenueOrThrow(venueId);
    venue.status = 'closed';
  }

  forceClose(venueId: string): void {
    const venue = this.venues.get(venueId);
    if (venue) venue.status = 'closed';
  }

  /** Close any venues whose TTL has expired */
  pruneExpired(): string[] {
    const now = Date.now();
    const closed: string[] = [];
    for (const [id, venue] of this.venues) {
      if (venue.expiresAt && now > venue.expiresAt && venue.status !== 'closed') {
        venue.status = 'closed';
        closed.push(id);
      }
    }
    return closed;
  }

  // ----------------------------------------------------------
  // Queries
  // ----------------------------------------------------------

  get(venueId: string): Venue | undefined {
    return this.venues.get(venueId);
  }

  getAll(): Venue[] {
    return [...this.venues.values()];
  }

  getActive(): Venue[] {
    return this.getAll().filter(v => v.status === 'active');
  }

  getMember(venueId: string, agentId: string): VenueMember | undefined {
    return this.venues.get(venueId)?.members.find(m => m.agentId === agentId);
  }

  getSupervisor(venue: Venue, agentId: string): VenueMember | undefined {
    const member = venue.members.find(m => m.agentId === agentId);
    if (!member?.supervisorId) return undefined;
    return venue.members.find(m => m.agentId === member.supervisorId);
  }

  getSubordinates(venue: Venue, agentId: string): VenueMember[] {
    const member = venue.members.find(m => m.agentId === agentId);
    if (!member?.subordinateIds?.length) return [];
    return venue.members.filter(m => member.subordinateIds!.includes(m.agentId));
  }

  // ----------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------

  private getVenueOrThrow(venueId: string): Venue {
    const venue = this.venues.get(venueId);
    if (!venue) throw new Error(`Venue ${venueId} not found`);
    return venue;
  }

  /**
   * Wire supervisor/subordinate relationships based on the reporting chain
   * and each member's role.
   */
  private wireHierarchy(
    members: VenueMember[],
    reportingChain: Record<string, string>,
  ): void {
    // Reset
    for (const m of members) {
      m.supervisorId = undefined;
      m.subordinateIds = [];
    }

    for (const member of members) {
      const supervisorRole = reportingChain[member.role];
      if (!supervisorRole) continue;

      // Find the first member with the supervisor role
      const supervisor = members.find(m => m.role === supervisorRole);
      if (!supervisor) continue;

      member.supervisorId = supervisor.agentId;
      if (!supervisor.subordinateIds) supervisor.subordinateIds = [];
      if (!supervisor.subordinateIds.includes(member.agentId)) {
        supervisor.subordinateIds.push(member.agentId);
      }
    }
  }
}
