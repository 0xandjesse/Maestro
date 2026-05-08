// ============================================================
// Maestro Protocol — Stage Manager
// ============================================================
//
// Manages Stage lifecycle: creation, member management,
// permission enforcement, role assignment, and closure.
//
// This is an in-process implementation suitable for local mode
// and testing. Network mode stages delegate to a platform
// host (e.g. TaskMaster API).
// ============================================================

import { randomUUID } from 'crypto';
import {
  CreateStageRequest,
  JoinRequest,
  JoinResponse,
  Permission,
  PermissionCheckResult,
  RoleTransferRequest,
  Stage,
  StageMember,
  StageRules,
  StageStatus,
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
    'stage:close',
    'stage:transfer',
  ],
  worker: [
    'message:send',
    'message:broadcast',  // Workers can broadcast in open/peer Stages
    'blackboard:read',
    'blackboard:write',
  ],
  observer: [
    'blackboard:read',
  ],
};

// ----------------------------------------------------------
// StageManager
// ----------------------------------------------------------

export class StageManager {
  private stages = new Map<string, Stage>();

  // ----------------------------------------------------------
  // Create
  // ----------------------------------------------------------

  create(request: CreateStageRequest, hostId: string): Stage {
    const id = randomUUID();
    const now = Date.now();

    const members: StageMember[] = [];

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

    const stage: Stage = {
      id,
      name: request.name,
      hostId,
      rules: request.rules,
      members,
      createdAt: now,
      status: members.length > 1 ? 'active' : 'created',
      ...(request.expiresAt ? { expiresAt: request.expiresAt } : {}),
    };

    this.stages.set(id, stage);
    return stage;
  }

  // ----------------------------------------------------------
  // Join
  // ----------------------------------------------------------

  processJoin(stageId: string, request: JoinRequest): JoinResponse {
    const stage = this.stages.get(stageId);
    if (!stage) {
      return { status: 'rejected', reason: 'stage_not_found' };
    }

    if (stage.status === 'closed') {
      return { status: 'rejected', reason: 'stage_closed' };
    }

    const rules = stage.rules;

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
    if (rules.maxMembers && stage.members.length >= rules.maxMembers) {
      return { status: 'rejected', reason: 'stage_full' };
    }

    // Already a member?
    if (stage.members.find(m => m.agentId === request.agentId)) {
      return { status: 'rejected', reason: 'already_member' };
    }

    // Add member with default role
    const defaultRole = rules.hierarchy?.defaultRole ?? 'worker';
    const member: StageMember = {
      agentId: request.agentId,
      role: defaultRole,
      joinedAt: Date.now(),
      capabilities: request.capabilities,
      subordinateIds: [],
    };

    stage.members.push(member);
    stage.status = 'active';

    // Wire up hierarchy for new member
    if (rules.hierarchy) {
      this.wireHierarchy(stage.members, rules.hierarchy.reportingChain);
    }

    const supervisor = this.getSupervisor(stage, request.agentId);

    return {
      status: 'accepted',
      stageId: stage.id,
      role: defaultRole,
      supervisorId: supervisor?.agentId,
      members: this.visibleMembers(stage, request.agentId),
      rules: stage.rules,
    };
  }

  // ----------------------------------------------------------
  // Permission Checks
  // ----------------------------------------------------------

  checkPermission(
    stageId: string,
    agentId: string,
    permission: Permission,
  ): PermissionCheckResult {
    const stage = this.stages.get(stageId);
    if (!stage) return { allowed: false, reason: 'stage_not_found' };
    if (stage.status === 'closed') return { allowed: false, reason: 'stage_closed' };

    const member = stage.members.find(m => m.agentId === agentId);
    if (!member) return { allowed: false, reason: 'not_a_member' };

    const rolePermissions = stage.rules.permissions[member.role] ?? [];
    if (rolePermissions.includes(permission)) {
      return { allowed: true };
    }

    return {
      allowed: false,
      reason: `role '${member.role}' lacks permission '${permission}'`,
    };
  }

  requirePermission(stageId: string, agentId: string, permission: Permission): void {
    const result = this.checkPermission(stageId, agentId, permission);
    if (!result.allowed) {
      throw new Error(`Permission denied: ${result.reason}`);
    }
  }

  // ----------------------------------------------------------
  // Role Management
  // ----------------------------------------------------------

  assignRole(
    stageId: string,
    requestingAgentId: string,
    targetAgentId: string,
    newRole: string,
  ): void {
    this.requirePermission(stageId, requestingAgentId, 'role:assign');

    const stage = this.getStageOrThrow(stageId);

    const validRoles = stage.rules.hierarchy?.roles ?? Object.keys(stage.rules.permissions);
    if (!validRoles.includes(newRole)) {
      throw new Error(`Unknown role: ${newRole}`);
    }

    const member = stage.members.find(m => m.agentId === targetAgentId);
    if (!member) throw new Error(`Agent ${targetAgentId} is not a member of stage ${stageId}`);

    member.role = newRole;

    // Re-wire hierarchy after role change
    if (stage.rules.hierarchy) {
      this.wireHierarchy(stage.members, stage.rules.hierarchy.reportingChain);
    }
  }

  transferRole(
    stageId: string,
    requestingAgentId: string,
    request: RoleTransferRequest,
  ): void {
    this.requirePermission(stageId, requestingAgentId, 'stage:transfer');
    const stage = this.getStageOrThrow(stageId);

    const requester = stage.members.find(m => m.agentId === requestingAgentId);
    const target = stage.members.find(m => m.agentId === request.to);

    if (!requester) throw new Error('Requester not found');
    if (!target) throw new Error(`Transfer target ${request.to} is not a member`);

    const prevRole = requester.role;
    const defaultRole = stage.rules.hierarchy?.defaultRole ?? 'worker';

    // Swap roles
    requester.role = defaultRole;
    target.role = request.role;

    // Update host if lead transferred
    if (prevRole === stage.rules.hierarchy?.roles[0]) {
      stage.hostId = request.to;
    }

    if (stage.rules.hierarchy) {
      this.wireHierarchy(stage.members, stage.rules.hierarchy.reportingChain);
    }
  }

  // ----------------------------------------------------------
  // Member Management
  // ----------------------------------------------------------

  removeMember(stageId: string, requestingAgentId: string, targetAgentId: string): void {
    this.requirePermission(stageId, requestingAgentId, 'member:remove');
    const stage = this.getStageOrThrow(stageId);

    if (targetAgentId === stage.hostId) {
      throw new Error('Cannot remove the Stage host. Transfer ownership first.');
    }

    stage.members = stage.members.filter(m => m.agentId !== targetAgentId);

    if (stage.rules.hierarchy) {
      this.wireHierarchy(stage.members, stage.rules.hierarchy.reportingChain);
    }
  }

  leave(stageId: string, agentId: string): void {
    const stage = this.getStageOrThrow(stageId);
    if (agentId === stage.hostId) {
      throw new Error('Host cannot leave. Close or transfer the Stage first.');
    }
    stage.members = stage.members.filter(m => m.agentId !== agentId);
  }

  // ----------------------------------------------------------
  // Visibility
  // ----------------------------------------------------------

  /**
   * Returns the list of members visible to a given agent,
   * respecting the Stage's memberVisibility setting.
   */
  visibleMembers(stage: Stage, agentId: string): StageMember[] {
    switch (stage.rules.memberVisibility) {
      case 'all':
        return [...stage.members];

      case 'hierarchy': {
        const member = stage.members.find(m => m.agentId === agentId);
        if (!member) return [];
        const supervisorId = member.supervisorId;
        return stage.members.filter(m => {
          if (m.agentId === agentId) return true;
          if (m.agentId === supervisorId) return true;
          if (member.subordinateIds?.includes(m.agentId)) return true;
          if (supervisorId && m.supervisorId === supervisorId) return true;
          return false;
        });
      }

      case 'role-based': {
        const member = stage.members.find(m => m.agentId === agentId);
        if (!member) return [];
        return stage.members.filter(m => {
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

  close(stageId: string, requestingAgentId: string): void {
    this.requirePermission(stageId, requestingAgentId, 'stage:close');
    const stage = this.getStageOrThrow(stageId);
    stage.status = 'closed';
  }

  forceClose(stageId: string): void {
    const stage = this.stages.get(stageId);
    if (stage) stage.status = 'closed';
  }

  /** Close any stages whose TTL has expired */
  pruneExpired(): string[] {
    const now = Date.now();
    const closed: string[] = [];
    for (const [id, stage] of this.stages) {
      if (stage.expiresAt && now > stage.expiresAt && stage.status !== 'closed') {
        stage.status = 'closed';
        closed.push(id);
      }
    }
    return closed;
  }

  // ----------------------------------------------------------
  // Queries
  // ----------------------------------------------------------

  get(stageId: string): Stage | undefined {
    return this.stages.get(stageId);
  }

  getAll(): Stage[] {
    return [...this.stages.values()];
  }

  getActive(): Stage[] {
    return this.getAll().filter(v => v.status === 'active');
  }

  getMember(stageId: string, agentId: string): StageMember | undefined {
    return this.stages.get(stageId)?.members.find(m => m.agentId === agentId);
  }

  getSupervisor(stage: Stage, agentId: string): StageMember | undefined {
    const member = stage.members.find(m => m.agentId === agentId);
    if (!member?.supervisorId) return undefined;
    return stage.members.find(m => m.agentId === member.supervisorId);
  }

  getSubordinates(stage: Stage, agentId: string): StageMember[] {
    const member = stage.members.find(m => m.agentId === agentId);
    if (!member?.subordinateIds?.length) return [];
    return stage.members.filter(m => member.subordinateIds!.includes(m.agentId));
  }

  // ----------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------

  private getStageOrThrow(stageId: string): Stage {
    const stage = this.stages.get(stageId);
    if (!stage) throw new Error(`Stage ${stageId} not found`);
    return stage;
  }

  /**
   * Wire supervisor/subordinate relationships based on the reporting chain
   * and each member's role.
   */
  private wireHierarchy(
    members: StageMember[],
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
