// ============================================================
// Maestro Protocol - Connection Manager
// ============================================================
//
// Manages Connection lifecycle: creation, member management,
// permission enforcement, role assignment, and closure.
//
// This is an in-process implementation suitable for local mode
// and testing. Network mode connections delegate to a platform
// host (e.g. TaskMaster API).
// ============================================================

import { randomUUID } from 'crypto';
import {
  CreateConnectionRequest,
  JoinRequest,
  JoinResponse,
  Permission,
  PermissionCheckResult,
  RoleTransferRequest,
  Connection,
  ConnectionMember,
  ConnectionRules,
  ConnectionStatus,
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
// ConnectionManager
// ----------------------------------------------------------

export class ConnectionManager {
  private connections = new Map<string, Connection>();

  // ----------------------------------------------------------
  // Create
  // ----------------------------------------------------------

  create(request: CreateConnectionRequest, hostId: string): Connection {
    const id = randomUUID();
    const now = Date.now();

    const members: ConnectionMember[] = [];

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

    const connection: Connection = {
      id,
      name: request.name,
      hostId,
      rules: request.rules,
      members,
      createdAt: now,
      status: members.length > 1 ? 'active' : 'created',
      ...(request.expiresAt ? { expiresAt: request.expiresAt } : {}),
    };

    this.connections.set(id, connection);
    return connection;
  }

  // ----------------------------------------------------------
  // Join
  // ----------------------------------------------------------

  processJoin(connectionId: string, request: JoinRequest): JoinResponse {
    const connection = this.connections.get(connectionId);
    if (!connection) {
      return { status: 'rejected', reason: 'venue_not_found' };
    }

    if (connection.status === 'closed') {
      return { status: 'rejected', reason: 'venue_closed' };
    }

    const rules = connection.rules;

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
    if (rules.maxMembers && connection.members.length >= rules.maxMembers) {
      return { status: 'rejected', reason: 'venue_full' };
    }

    // Already a member?
    if (connection.members.find(m => m.agentId === request.agentId)) {
      return { status: 'rejected', reason: 'already_member' };
    }

    // Add member with default role
    const defaultRole = rules.hierarchy?.defaultRole ?? 'worker';
    const member: ConnectionMember = {
      agentId: request.agentId,
      role: defaultRole,
      joinedAt: Date.now(),
      capabilities: request.capabilities,
      subordinateIds: [],
    };

    connection.members.push(member);
    connection.status = 'active';

    // Wire up hierarchy for new member
    if (rules.hierarchy) {
      this.wireHierarchy(connection.members, rules.hierarchy.reportingChain);
    }

    const supervisor = this.getSupervisor(connection, request.agentId);

    return {
      status: 'accepted',
      connectionId: connection.id,
      name: connection.name,
      hostAgentId: connection.hostId,
      role: defaultRole,
      supervisorId: supervisor?.agentId,
      members: this.visibleMembers(connection, request.agentId),
      rules: connection.rules,
    };
  }

  // ----------------------------------------------------------
  // Permission Checks
  // ----------------------------------------------------------

  checkPermission(
    connectionId: string,
    agentId: string,
    permission: Permission,
  ): PermissionCheckResult {
    const connection = this.connections.get(connectionId);
    if (!connection) return { allowed: false, reason: 'venue_not_found' };
    if (connection.status === 'closed') return { allowed: false, reason: 'venue_closed' };

    const member = connection.members.find(m => m.agentId === agentId);
    if (!member) return { allowed: false, reason: 'not_a_member' };

    const rolePermissions = connection.rules.permissions[member.role] ?? [];
    if (rolePermissions.includes(permission)) {
      return { allowed: true };
    }

    return {
      allowed: false,
      reason: `role '${member.role}' lacks permission '${permission}'`,
    };
  }

  requirePermission(connectionId: string, agentId: string, permission: Permission): void {
    const result = this.checkPermission(connectionId, agentId, permission);
    if (!result.allowed) {
      throw new Error(`Permission denied: ${result.reason}`);
    }
  }

  // ----------------------------------------------------------
  // Role Management
  // ----------------------------------------------------------

  assignRole(
    connectionId: string,
    requestingAgentId: string,
    targetAgentId: string,
    newRole: string,
  ): void {
    this.requirePermission(connectionId, requestingAgentId, 'role:assign');

    const connection = this.getConnectionOrThrow(connectionId);

    const validRoles = connection.rules.hierarchy?.roles ?? Object.keys(connection.rules.permissions);
    if (!validRoles.includes(newRole)) {
      throw new Error(`Unknown role: ${newRole}`);
    }

    const member = connection.members.find(m => m.agentId === targetAgentId);
    if (!member) throw new Error(`Agent ${targetAgentId} is not a member of connection ${connectionId}`);

    member.role = newRole;

    // Re-wire hierarchy after role change
    if (connection.rules.hierarchy) {
      this.wireHierarchy(connection.members, connection.rules.hierarchy.reportingChain);
    }
  }

  transferRole(
    connectionId: string,
    requestingAgentId: string,
    request: RoleTransferRequest,
  ): void {
    this.requirePermission(connectionId, requestingAgentId, 'venue:transfer');
    const connection = this.getConnectionOrThrow(connectionId);

    const requester = connection.members.find(m => m.agentId === requestingAgentId);
    const target = connection.members.find(m => m.agentId === request.to);

    if (!requester) throw new Error('Requester not found');
    if (!target) throw new Error(`Transfer target ${request.to} is not a member`);

    const prevRole = requester.role;
    const defaultRole = connection.rules.hierarchy?.defaultRole ?? 'worker';

    // Swap roles
    requester.role = defaultRole;
    target.role = request.role;

    // Update host if lead transferred
    if (prevRole === connection.rules.hierarchy?.roles[0]) {
      connection.hostId = request.to;
    }

    if (connection.rules.hierarchy) {
      this.wireHierarchy(connection.members, connection.rules.hierarchy.reportingChain);
    }
  }

  // ----------------------------------------------------------
  // Member Management
  // ----------------------------------------------------------

  removeMember(connectionId: string, requestingAgentId: string, targetAgentId: string): void {
    this.requirePermission(connectionId, requestingAgentId, 'member:remove');
    const connection = this.getConnectionOrThrow(connectionId);

    if (targetAgentId === connection.hostId) {
      throw new Error('Cannot remove the Connection host. Transfer ownership first.');
    }

    connection.members = connection.members.filter(m => m.agentId !== targetAgentId);

    if (connection.rules.hierarchy) {
      this.wireHierarchy(connection.members, connection.rules.hierarchy.reportingChain);
    }
  }

  leave(connectionId: string, agentId: string): void {
    const connection = this.getConnectionOrThrow(connectionId);
    if (agentId === connection.hostId) {
      throw new Error('Host cannot leave. Close or transfer the Connection first.');
    }
    connection.members = connection.members.filter(m => m.agentId !== agentId);
  }

  // ----------------------------------------------------------
  // Visibility
  // ----------------------------------------------------------

  /**
   * Returns the list of members visible to a given agent,
   * respecting the Connection's memberVisibility setting.
   */
  visibleMembers(connection: Connection, agentId: string): ConnectionMember[] {
    switch (connection.rules.memberVisibility) {
      case 'all':
        return [...connection.members];

      case 'hierarchy': {
        const member = connection.members.find(m => m.agentId === agentId);
        if (!member) return [];
        // Can see: own supervisor + own subordinates + peers under same supervisor
        const supervisorId = member.supervisorId;
        return connection.members.filter(m => {
          if (m.agentId === agentId) return true;
          if (m.agentId === supervisorId) return true;
          if (member.subordinateIds?.includes(m.agentId)) return true;
          // Peers: same supervisor
          if (supervisorId && m.supervisorId === supervisorId) return true;
          return false;
        });
      }

      case 'role-based': {
        const member = connection.members.find(m => m.agentId === agentId);
        if (!member) return [];
        // Same role can see each other + supervisors
        return connection.members.filter(m => {
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

  close(connectionId: string, requestingAgentId: string): void {
    this.requirePermission(connectionId, requestingAgentId, 'venue:close');
    const connection = this.getConnectionOrThrow(connectionId);
    connection.status = 'closed';
  }

  forceClose(connectionId: string): void {
    const connection = this.connections.get(connectionId);
    if (connection) connection.status = 'closed';
  }

  /** Close any connections whose TTL has expired */
  pruneExpired(): string[] {
    const now = Date.now();
    const closed: string[] = [];
    for (const [id, connection] of this.connections) {
      if (connection.expiresAt && now > connection.expiresAt && connection.status !== 'closed') {
        connection.status = 'closed';
        closed.push(id);
      }
    }
    return closed;
  }

  // ----------------------------------------------------------
  // Queries
  // ----------------------------------------------------------

  /**
   * Mirror a remote Connection into this ConnectionManager.
   * Used by guest agents after a successful network join so that
   * local permission checks and member queries work correctly.
   * No-op if the connectionId is already registered.
   */
  mirrorConnection(
    connectionId: string,
    name: string,
    hostId: string,
    rules: ConnectionRules,
    members: ConnectionMember[],
  ): void {
    if (this.connections.has(connectionId)) return; // already registered
    const connection: Connection = {
      id: connectionId,
      name,
      hostId,
      rules,
      members: [...members],
      createdAt: Date.now(),
      status: 'active',
    };
    this.connections.set(connectionId, connection);
  }

  get(connectionId: string): Connection | undefined {
    return this.connections.get(connectionId);
  }

  getAll(): Connection[] {
    return [...this.connections.values()];
  }

  getActive(): Connection[] {
    return this.getAll().filter(s => s.status === 'active');
  }

  getMember(connectionId: string, agentId: string): ConnectionMember | undefined {
    return this.connections.get(connectionId)?.members.find(m => m.agentId === agentId);
  }

  getSupervisor(connection: Connection, agentId: string): ConnectionMember | undefined {
    const member = connection.members.find(m => m.agentId === agentId);
    if (!member?.supervisorId) return undefined;
    return connection.members.find(m => m.agentId === member.supervisorId);
  }

  getSubordinates(connection: Connection, agentId: string): ConnectionMember[] {
    const member = connection.members.find(m => m.agentId === agentId);
    if (!member?.subordinateIds?.length) return [];
    return connection.members.filter(m => member.subordinateIds!.includes(m.agentId));
  }

  // ----------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------

  private getConnectionOrThrow(connectionId: string): Connection {
    const connection = this.connections.get(connectionId);
    if (!connection) throw new Error(`Connection ${connectionId} not found`);
    return connection;
  }

  /**
   * Wire supervisor/subordinate relationships based on the reporting chain
   * and each member's role.
   */
  private wireHierarchy(
    members: ConnectionMember[],
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
