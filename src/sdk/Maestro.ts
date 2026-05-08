// ============================================================
// Maestro Protocol — SDK Entry Point
// ============================================================
//
// The Maestro class is what agents import and instantiate.
// It wires together: StageManager, MessageRouter, Blackboard,
// and discovery.
//
// Usage:
//   const maestro = new Maestro({ agentId: 'hermes', ... });
//   await maestro.start();
//   const stage = maestro.createStage({ ... });
//   await stage.send('lex', 'API spec is ready');
// ============================================================

import { randomUUID } from 'crypto';
import { MaestroMessage, MessageType } from '../types/index.js';
import { StageManager, DEFAULT_PERMISSIONS } from '../stage/StageManager.js';
import {
  CreateStageRequest,
  JoinRequest,
  JoinResponse,
  Permission,
  Stage,
  StageMember,
  StageRules,
} from '../stage/types.js';
import { InMemoryBlackboard } from '../blackboard/InMemoryBlackboard.js';
import { SqliteBlackboard } from '../blackboard/SqliteBlackboard.js';
import { SharedBlackboard } from '../blackboard/types.js';
import { MessageRouter } from '../transport/MessageRouter.js';
import { WebhookServer } from '../transport/WebhookServer.js';
import { NetworkTransport } from '../transport/NetworkTransport.js';
import { LocalRegistry } from '../transport/LocalRegistry.js';
import { MdnsRegistry } from '../transport/MdnsRegistry.js';
import {
  MaestroConfig,
  MessageHandler,
  SendOptions,
} from '../transport/types.js';
import { enforceProvenancePolicy } from '../stage/provenanceEnforcer.js';

// ----------------------------------------------------------
// StageHandle — what agents interact with per-Stage
// ----------------------------------------------------------

export class StageHandle {
  private maestro: Maestro;
  private hostManager: StageManager | undefined;
  readonly stageId: string;
  readonly blackboard: SharedBlackboard;

  constructor(maestro: Maestro, stageId: string, blackboard: SharedBlackboard, hostManager?: StageManager) {
    this.maestro = maestro;
    this.stageId = stageId;
    this.blackboard = blackboard;
    this.hostManager = hostManager;
  }

  private get manager(): StageManager {
    return this.hostManager ?? this.maestro.stageManager;
  }

  // ----------------------------------------------------------
  // Messaging
  // ----------------------------------------------------------

  /** Send a direct message to a specific agent in this Stage */
  async send(recipientId: string, content: string, options: SendOptions = {}): Promise<MaestroMessage> {
    this.requirePermission('message:send');
    return this.maestro.router.buildMessage('direct', content, recipientId, {
      ...options,
      stageId: this.stageId,
    });
  }

  /** Broadcast to all Stage members */
  async broadcast(content: string, options: SendOptions = {}): Promise<MaestroMessage> {
    this.requirePermission('message:broadcast');
    return this.maestro.router.buildMessage('broadcast', content, '*', {
      ...options,
      stageId: this.stageId,
    });
  }

  /** Report to supervisor (hierarchy Stages) */
  async reportTo(content: string, options: SendOptions = {}): Promise<MaestroMessage> {
    this.requirePermission('message:send');
    const stage = this.getStage();
    const supervisor = this.manager.getSupervisor(stage, this.maestro.agentId);
    if (!supervisor) throw new Error('No supervisor in this Stage.');
    return this.maestro.router.buildMessage('report', content, supervisor.agentId, {
      ...options,
      stageId: this.stageId,
    });
  }

  /** Assign work to a subordinate (hierarchy Stages) */
  async assignTo(subordinateId: string, content: string, options: SendOptions = {}): Promise<MaestroMessage> {
    this.requirePermission('message:send');
    return this.maestro.router.buildMessage('assign', content, subordinateId, {
      ...options,
      stageId: this.stageId,
    });
  }

  // ----------------------------------------------------------
  // Message handling
  // ----------------------------------------------------------

  /** Register a handler for messages in this Stage */
  on(type: MessageType | '*', handler: MessageHandler): void {
    this.maestro.router.on(type, (msg) => {
      if (msg.stageId === this.stageId) handler(msg);
    });
  }

  // ----------------------------------------------------------
  // Member management
  // ----------------------------------------------------------

  getMembers(): StageMember[] {
    return this.manager.visibleMembers(this.getStage(), this.maestro.agentId);
  }

  getMember(agentId: string): StageMember | undefined {
    return this.manager.getMember(this.stageId, agentId);
  }

  assignRole(targetAgentId: string, role: string): void {
    this.manager.assignRole(this.stageId, this.maestro.agentId, targetAgentId, role);
  }

  removeMember(agentId: string): void {
    this.manager.removeMember(this.stageId, this.maestro.agentId, agentId);
  }

  transferRole(role: string, toAgentId: string, reason?: string): void {
    this.manager.transferRole(this.stageId, this.maestro.agentId, {
      role, to: toAgentId, reason,
    });
  }

  // ----------------------------------------------------------
  // Lifecycle
  // ----------------------------------------------------------

  /** Leave this Stage */
  async leave(): Promise<void> {
    this.manager.leave(this.stageId, this.maestro.agentId);
    this.maestro.removeStageHandle(this.stageId);
  }

  /** Close this Stage (lead/host only) */
  async close(): Promise<void> {
    this.manager.close(this.stageId, this.maestro.agentId);
    this.maestro.removeStageHandle(this.stageId);
  }

  // ----------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------

  getStageInfo(): Stage {
    return this.getStage();
  }

  private getStage(): Stage {
    const s = this.manager.get(this.stageId);
    if (!s) throw new Error(`Stage ${this.stageId} not found`);
    return s;
  }

  private requirePermission(permission: Permission): void {
    this.manager.requirePermission(this.stageId, this.maestro.agentId, permission);
  }
}

// ----------------------------------------------------------
// Maestro SDK
// ----------------------------------------------------------

export class Maestro {
  readonly agentId: string;
  readonly stageManager: StageManager;
  readonly router: MessageRouter;

  private config: MaestroConfig;
  private stageHandles = new Map<string, StageHandle>();
  private blackboards = new Map<string, SharedBlackboard>();
  private started = false;
  private webhookServer?: WebhookServer;
  readonly network: NetworkTransport;
  private registry?: LocalRegistry;
  private mdns?: MdnsRegistry;

  constructor(config: MaestroConfig) {
    this.config = config;
    this.agentId = config.agentId;
    this.stageManager = new StageManager();
    this.router = new MessageRouter(config.agentId, this.stageManager);
    this.network = new NetworkTransport();
  }

  // ----------------------------------------------------------
  // Lifecycle
  // ----------------------------------------------------------

  async start(): Promise<void> {
    if (this.started) return;
    this.started = true;

    // Start webhook server if a port is configured
    if (this.config.webhookPort) {
      this.webhookServer = new WebhookServer({
        port: this.config.webhookPort,
        path: this.config.webhookPath,
        agentId: this.agentId,
        onMessage: (msg) => this.receive(msg),
      });
      await this.webhookServer.start();
    }

    // Register with file-based discovery if configured
    if (this.config.discovery?.method === 'file' && this.config.discovery.filePath) {
      this.registry = new LocalRegistry(this.config.discovery.filePath);
      this.registry.register({
        agentId: this.agentId,
        webhookEndpoint: this.webhookEndpoint,
        publicKey: this.config.publicKey,
        wallet: this.config.wallet,
        capabilities: [],
      });
    }

    // Start mDNS discovery if configured
    if (this.config.discovery?.method === 'mdns' && this.config.webhookPort) {
      this.mdns = new MdnsRegistry({
        agentId: this.agentId,
        port: this.config.webhookPort,
        webhookPath: this.config.webhookPath,
        publicKey: this.config.publicKey,
        wallet: this.config.wallet,
      });
      this.mdns.start();
    }
  }

  async stop(): Promise<void> {
    if (!this.started) return;
    this.started = false;

    if (this.registry) {
      this.registry.unregister(this.agentId);
    }
    if (this.mdns) {
      this.mdns.stop();
    }
    if (this.webhookServer) {
      await this.webhookServer.stop();
    }
  }

  /** The webhook URL other agents should POST messages to */
  get webhookEndpoint(): string {
    if (this.webhookServer) return this.webhookServer.endpoint;
    const port = this.config.webhookPort ?? 3001;
    const path = this.config.webhookPath ?? '/maestro/webhook';
    return `http://localhost:${port}${path}`;
  }

  /**
   * Send a message to a remote agent by webhook endpoint.
   * Use this for cross-process delivery.
   */
  async sendRemote(message: ReturnType<MessageRouter['buildMessage']>, recipientEndpoint: string) {
    return this.network.send(message, recipientEndpoint);
  }

  /**
   * Look up a registered agent's endpoint.
   * Checks file registry first, then mDNS peer list.
   */
  lookupAgent(agentId: string) {
    return this.registry?.lookup(agentId) ?? this.mdns?.lookupPeer(agentId);
  }

  /** Access the mDNS registry (if active) to list discovered peers */
  get peers() {
    return this.mdns?.listPeers() ?? [];
  }

  /** Trigger an active mDNS query to find peers on the local network */
  discoverPeers(): void {
    this.mdns?.query();
  }

  // ----------------------------------------------------------
  // Stage Management
  // ----------------------------------------------------------

  /** Create a new Stage and return a handle to it */
  createStage(request: CreateStageRequest): StageHandle {
    const stage = this.stageManager.create(request, this.agentId);
    return this.makeHandle(stage.id);
  }

  /**
   * Create a Stage with sensible defaults.
   * Shortcut for common "open peer" or "hierarchical" setups.
   */
  createOpenStage(name: string): StageHandle {
    return this.createStage({
      name,
      rules: {
        entryMode: 'open',
        memberVisibility: 'all',
        permissions: {
          lead: [...DEFAULT_PERMISSIONS.lead],
          worker: [...DEFAULT_PERMISSIONS.worker],
        },
      },
    });
  }

  createHierarchicalStage(
    name: string,
    roles: string[],
    reportingChain: Record<string, string>,
  ): StageHandle {
    const permissions: Record<string, Permission[]> = {};
    roles.forEach((role, i) => {
      if (i === 0) {
        permissions[role] = [...DEFAULT_PERMISSIONS.lead];
      } else {
        permissions[role] = [...DEFAULT_PERMISSIONS.worker];
      }
    });

    return this.createStage({
      name,
      rules: {
        entryMode: 'assignment',
        memberVisibility: 'hierarchy',
        hierarchy: {
          roles,
          reportingChain,
          defaultRole: roles[roles.length - 1],
        },
        permissions,
      },
    });
  }

  /**
   * Join an existing Stage by ID.
   *
   * In local mode (same process), pass the host's StageManager so this
   * agent's join request is processed against the correct Stage store.
   * In network mode, the join request is sent over HTTP to the host.
   *
   * @param stageId       The Stage to join
   * @param hostManager   The StageManager that owns the Stage (local mode)
   * @param options       Additional join options
   */
  join(
    stageId: string,
    hostManager?: StageManager,
    options: Partial<JoinRequest> = {},
  ): JoinResponse {
    const request: JoinRequest = {
      protocolVersion: '3.2',
      agentId: this.agentId,
      identity: {
        wallet: this.config.wallet,
        publicKey: this.config.publicKey,
      },
      webhookEndpoint: `http://localhost:${this.config.webhookPort ?? 3001}/maestro/webhook`,
      capabilities: [],
      ...options,
    };

    const manager = hostManager ?? this.stageManager;
    const response = manager.processJoin(stageId, request);

    if (response.status === 'accepted') {
      if (hostManager) {
        const stage = hostManager.get(stageId);
        if (stage) {
          this._sharedManagers.set(stageId, hostManager);
        }
      }
      this.makeHandle(stageId, hostManager);
    }

    return response;
  }

  /** @internal Shared StageManager references for locally-joined Stages */
  private _sharedManagers = new Map<string, StageManager>();

  /** @internal Get the authoritative StageManager for a Stage */
  getManagerForStage(stageId: string): StageManager {
    return this._sharedManagers.get(stageId) ?? this.stageManager;
  }

  getStage(stageId: string): StageHandle | undefined {
    return this.stageHandles.get(stageId);
  }

  listStages(): StageHandle[] {
    return [...this.stageHandles.values()];
  }

  // ----------------------------------------------------------
  // Message Routing (global)
  // ----------------------------------------------------------

  /** Register a global message handler (all Venues) */
  onMessage(type: MessageType | '*', handler: MessageHandler): void {
    this.router.on(type, handler);
  }

  /** Dispatch an inbound message (called by webhook receiver) */
  async receive(message: MaestroMessage): Promise<{ accepted: boolean; reason?: string }> {
    return this.router.dispatch(message);
  }

  // ----------------------------------------------------------
  // Internal
  // ----------------------------------------------------------

  private makeHandle(stageId: string, hostManager?: StageManager): StageHandle {
    if (!this.blackboards.has(stageId)) {
      const bb = this.config.blackboardPath
        ? new SqliteBlackboard({ path: this.config.blackboardPath, stageId })
        : new InMemoryBlackboard();
      this.blackboards.set(stageId, bb);
    }
    const bb = this.blackboards.get(stageId)!;
    const handle = new StageHandle(this, stageId, bb, hostManager);
    this.stageHandles.set(stageId, handle);
    return handle;
  }

  removeStageHandle(stageId: string): void {
    this.stageHandles.delete(stageId);
  }

  getBlackboard(stageId: string): SharedBlackboard | undefined {
    return this.blackboards.get(stageId);
  }

  /**
   * Replace this agent's blackboard for a Stage with an externally-provided one.
   * Used for same-process joins to share a single blackboard instance across agents.
   */
  linkBlackboard(stageId: string, bb: SharedBlackboard): void {
    this.blackboards.set(stageId, bb);
    const hostManager = this._sharedManagers.get(stageId);
    const handle = new StageHandle(this, stageId, bb, hostManager);
    this.stageHandles.set(stageId, handle);
  }
}
