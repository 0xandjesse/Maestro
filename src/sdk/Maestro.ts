// ============================================================
// Maestro Protocol — SDK Entry Point
// ============================================================
//
// The Maestro class is what agents import and instantiate.
// It wires together: VenueManager, MessageRouter, Blackboard,
// and discovery.
//
// Usage:
//   const maestro = new Maestro({ agentId: 'hermes', ... });
//   await maestro.start();
//   const venue = maestro.createVenue({ ... });
//   await venue.send('lex', 'API spec is ready');
// ============================================================

import { randomUUID } from 'crypto';
import { MaestroMessage, MessageType } from '../types/index.js';
import { VenueManager, DEFAULT_PERMISSIONS } from '../venue/VenueManager.js';
import {
  CreateVenueRequest,
  JoinRequest,
  JoinResponse,
  Permission,
  Venue,
  VenueMember,
  VenueRules,
} from '../venue/types.js';
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
import { enforceProvenancePolicy } from '../venue/provenanceEnforcer.js';

// ----------------------------------------------------------
// VenueHandle — what agents interact with per-Venue
// ----------------------------------------------------------

export class VenueHandle {
  private maestro: Maestro;
  private hostManager: VenueManager | undefined;
  readonly venueId: string;
  readonly blackboard: SharedBlackboard;

  constructor(maestro: Maestro, venueId: string, blackboard: SharedBlackboard, hostManager?: VenueManager) {
    this.maestro = maestro;
    this.venueId = venueId;
    this.blackboard = blackboard;
    this.hostManager = hostManager;
  }

  private get manager(): VenueManager {
    return this.hostManager ?? this.maestro.venueManager;
  }

  // ----------------------------------------------------------
  // Messaging
  // ----------------------------------------------------------

  /** Send a direct message to a specific agent in this Venue */
  async send(recipientId: string, content: string, options: SendOptions = {}): Promise<MaestroMessage> {
    this.requirePermission('message:send');
    return this.maestro.router.buildMessage('direct', content, recipientId, {
      ...options,
      venueId: this.venueId,
    });
  }

  /** Broadcast to all Venue members */
  async broadcast(content: string, options: SendOptions = {}): Promise<MaestroMessage> {
    this.requirePermission('message:broadcast');
    return this.maestro.router.buildMessage('broadcast', content, '*', {
      ...options,
      venueId: this.venueId,
    });
  }

  /** Report to supervisor (hierarchy Venues) */
  async reportTo(content: string, options: SendOptions = {}): Promise<MaestroMessage> {
    this.requirePermission('message:send');
    const venue = this.getVenue();
    const supervisor = this.manager.getSupervisor(venue, this.maestro.agentId);
    if (!supervisor) throw new Error('No supervisor in this Venue.');
    return this.maestro.router.buildMessage('report', content, supervisor.agentId, {
      ...options,
      venueId: this.venueId,
    });
  }

  /** Assign work to a subordinate (hierarchy Venues) */
  async assignTo(subordinateId: string, content: string, options: SendOptions = {}): Promise<MaestroMessage> {
    this.requirePermission('message:send');
    return this.maestro.router.buildMessage('assign', content, subordinateId, {
      ...options,
      venueId: this.venueId,
    });
  }

  // ----------------------------------------------------------
  // Message handling
  // ----------------------------------------------------------

  /** Register a handler for messages in this Venue */
  on(type: MessageType | '*', handler: MessageHandler): void {
    this.maestro.router.on(type, (msg) => {
      if (msg.venueId === this.venueId) handler(msg);
    });
  }

  // ----------------------------------------------------------
  // Member management
  // ----------------------------------------------------------

  getMembers(): VenueMember[] {
    return this.manager.visibleMembers(this.getVenue(), this.maestro.agentId);
  }

  getMember(agentId: string): VenueMember | undefined {
    return this.manager.getMember(this.venueId, agentId);
  }

  assignRole(targetAgentId: string, role: string): void {
    this.manager.assignRole(this.venueId, this.maestro.agentId, targetAgentId, role);
  }

  removeMember(agentId: string): void {
    this.manager.removeMember(this.venueId, this.maestro.agentId, agentId);
  }

  transferRole(role: string, toAgentId: string, reason?: string): void {
    this.manager.transferRole(this.venueId, this.maestro.agentId, {
      role, to: toAgentId, reason,
    });
  }

  // ----------------------------------------------------------
  // Lifecycle
  // ----------------------------------------------------------

  /** Leave this Venue */
  async leave(): Promise<void> {
    this.manager.leave(this.venueId, this.maestro.agentId);
    this.maestro.removeVenueHandle(this.venueId);
  }

  /** Close this Venue (lead/host only) */
  async close(): Promise<void> {
    this.manager.close(this.venueId, this.maestro.agentId);
    this.maestro.removeVenueHandle(this.venueId);
  }

  // ----------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------

  getVenueInfo(): Venue {
    return this.getVenue();
  }

  private getVenue(): Venue {
    const v = this.manager.get(this.venueId);
    if (!v) throw new Error(`Venue ${this.venueId} not found`);
    return v;
  }

  private requirePermission(permission: Permission): void {
    this.manager.requirePermission(this.venueId, this.maestro.agentId, permission);
  }
}

// ----------------------------------------------------------
// Maestro SDK
// ----------------------------------------------------------

export class Maestro {
  readonly agentId: string;
  readonly venueManager: VenueManager;
  readonly router: MessageRouter;

  private config: MaestroConfig;
  private venueHandles = new Map<string, VenueHandle>();
  private blackboards = new Map<string, SharedBlackboard>();
  private started = false;
  private webhookServer?: WebhookServer;
  readonly network: NetworkTransport;
  private registry?: LocalRegistry;
  private mdns?: MdnsRegistry;

  constructor(config: MaestroConfig) {
    this.config = config;
    this.agentId = config.agentId;
    this.venueManager = new VenueManager();
    this.router = new MessageRouter(config.agentId, this.venueManager);
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
  // Venue Management
  // ----------------------------------------------------------

  /** Create a new Venue and return a handle to it */
  createVenue(request: CreateVenueRequest): VenueHandle {
    const venue = this.venueManager.create(request, this.agentId);
    return this.makeHandle(venue.id);
  }

  /**
   * Create a Venue with sensible defaults.
   * Shortcut for common "open peer" or "hierarchical" setups.
   */
  createOpenVenue(name: string): VenueHandle {
    return this.createVenue({
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

  createHierarchicalVenue(
    name: string,
    roles: string[],
    reportingChain: Record<string, string>,
  ): VenueHandle {
    const permissions: Record<string, Permission[]> = {};
    // Top role gets full permissions, others get progressively fewer
    roles.forEach((role, i) => {
      if (i === 0) {
        permissions[role] = [...DEFAULT_PERMISSIONS.lead];
      } else {
        permissions[role] = [...DEFAULT_PERMISSIONS.worker];
      }
    });

    return this.createVenue({
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
   * Join an existing Venue by ID.
   *
   * In local mode (same process), pass the host's VenueManager so this
   * agent's join request is processed against the correct Venue store.
   * In network mode, the join request is sent over HTTP to the host.
   *
   * @param venueId       The Venue to join
   * @param hostManager   The VenueManager that owns the Venue (local mode)
   * @param options       Additional join options
   */
  join(
    venueId: string,
    hostManager?: VenueManager,
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

    // Use the provided host VenueManager (local mode), or own (self-join / network mode)
    const manager = hostManager ?? this.venueManager;
    const response = manager.processJoin(venueId, request);

    if (response.status === 'accepted') {
      // Mirror the venue into this agent's manager so it can enforce permissions locally
      if (hostManager) {
        const venue = hostManager.get(venueId);
        if (venue) {
          // Store reference — use the host's VenueManager for all venue ops
          this._sharedManagers.set(venueId, hostManager);
        }
      }
      this.makeHandle(venueId, hostManager);
    }

    return response;
  }

  /** @internal Shared VenueManager references for locally-joined Venues */
  private _sharedManagers = new Map<string, VenueManager>();

  /** @internal Get the authoritative VenueManager for a Venue */
  getManagerForVenue(venueId: string): VenueManager {
    return this._sharedManagers.get(venueId) ?? this.venueManager;
  }

  getVenue(venueId: string): VenueHandle | undefined {
    return this.venueHandles.get(venueId);
  }

  listVenues(): VenueHandle[] {
    return [...this.venueHandles.values()];
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

  private makeHandle(venueId: string, hostManager?: VenueManager): VenueHandle {
    if (!this.blackboards.has(venueId)) {
      // Use SQLite if a path is configured, otherwise in-memory
      const bb = this.config.blackboardPath
        ? new SqliteBlackboard({ path: this.config.blackboardPath, venueId })
        : new InMemoryBlackboard();
      this.blackboards.set(venueId, bb);
    }
    const bb = this.blackboards.get(venueId)!;
    const handle = new VenueHandle(this, venueId, bb, hostManager);
    this.venueHandles.set(venueId, handle);
    return handle;
  }

  removeVenueHandle(venueId: string): void {
    this.venueHandles.delete(venueId);
  }

  getBlackboard(venueId: string): SharedBlackboard | undefined {
    return this.blackboards.get(venueId);
  }
}
