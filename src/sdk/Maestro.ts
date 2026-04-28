// ============================================================
// Maestro Protocol - SDK Entry Point
// ============================================================
//
// The Maestro class is what agents import and instantiate.
// It wires together: ConnectionManager, MessageRouter, Blackboard,
// and discovery.
//
// Usage:
//   const maestro = new Maestro({ agentId: 'hermes', ... });
//   await maestro.start();
//   const connection = maestro.createConnection({ ... });
//   await connection.send('lex', 'API spec is ready');
// ============================================================

import { randomUUID } from 'crypto';
import { MaestroMessage, MessageType } from '../types/index.js';
import { ConnectionManager, DEFAULT_PERMISSIONS } from '../connection/ConnectionManager.js';
import {
  CreateConnectionRequest,
  JoinRequest,
  JoinResponse,
  Permission,
  Connection,
  ConnectionMember,
  ConnectionRules,
} from '../connection/types.js';
import { InMemoryBlackboard } from '../blackboard/InMemoryBlackboard.js';
import { SQLiteBlackboard } from '../blackboard/SQLiteBlackboard.js';
import { BlackboardBridge } from '../blackboard/BlackboardBridge.js';
import { SharedBlackboard, BlackboardEntry, Unsubscribe } from '../blackboard/types.js';
import { MessageRouter } from '../transport/MessageRouter.js';
import { LocalRegistry } from '../transport/LocalRegistry.js';
import { HttpTransport } from '../transport/HttpTransport.js';
import { ConnectionBroker, ConnectionBrokerConfig, ConnectionInvitation } from '../transport/ConnectionBroker.js';
import { ConnectionStore, StoredConnection } from '../transport/ConnectionStore.js';
import { MdnsDiscovery } from '../transport/MdnsDiscovery.js';
import { OpenClawAdapter } from '../plugin/OpenClawAdapter.js';
import {
  MaestroConfig,
  MessageHandler,
  SendOptions,
} from '../transport/types.js';
import { enforceProvenancePolicy } from '../connection/provenanceEnforcer.js';

// ----------------------------------------------------------
// ConnectionHandle - what agents interact with per-Connection
// ----------------------------------------------------------

export class ConnectionHandle {
  private maestro: Maestro;
  private hostManager: ConnectionManager | undefined;
  private readonly _onRemove: () => void;
  readonly connectionId: string;
  readonly blackboard: SharedBlackboard;

  constructor(
    maestro: Maestro,
    connectionId: string,
    blackboard: SharedBlackboard,
    hostManager?: ConnectionManager,
    onRemove?: () => void,
  ) {
    this.maestro = maestro;
    this.connectionId = connectionId;
    this.blackboard = blackboard;
    this.hostManager = hostManager;
    this._onRemove = onRemove ?? (() => {});
  }

  // ----------------------------------------------------------
  // Blackboard convenience wrappers (with cross-process push)
  // ----------------------------------------------------------

  /** Write a value and notify all Connection members via transport. */
  async bbSet(key: string, value: unknown): Promise<void> {
    await this.blackboard.set(key, value, this.maestro.agentId);
    const entry = await this.blackboard.getEntry(key);
    if (entry && this.maestro.blackboardBridge) {
      const members = this.getMembers().map(m => m.agentId);
      this.maestro.blackboardBridge.notifyUpdate(this.connectionId, entry, members).catch((err: unknown) => {
        console.error('[ConnectionHandle] bbSet bridge error:', err);
      });
    }
  }

  /** Read a value from the blackboard. */
  async bbGet(key: string): Promise<unknown> {
    return this.blackboard.get(key);
  }

  /** Subscribe to changes on a specific key. Returns an unsubscribe function. */
  bbSubscribe(key: string, handler: (entry: BlackboardEntry) => void): Unsubscribe {
    return this.blackboard.subscribe(key, handler);
  }

  private get manager(): ConnectionManager {
    return this.hostManager ?? this.maestro.connectionManager;
  }

  // ----------------------------------------------------------
  // Messaging
  // ----------------------------------------------------------

  /** Send a direct message to a specific agent in this Connection */
  async send(recipientId: string, content: string, options: SendOptions = {}): Promise<MaestroMessage> {
    this.requirePermission('message:send');
    const message = this.maestro.router.buildMessage('direct', content, recipientId, {
      ...options,
      stageId: this.connectionId,
    });
    // Deliver via transport if available
    if (this.maestro.httpTransport) {
      await this.maestro.httpTransport.send(message).catch((err: unknown) => {
        console.error('[ConnectionHandle] Transport delivery error:', err);
      });
    }
    return message;
  }

  /** Broadcast to all Connection members */
  async broadcast(content: string, options: SendOptions = {}): Promise<MaestroMessage> {
    this.requirePermission('message:broadcast');
    const message = this.maestro.router.buildMessage('broadcast', content, '*', {
      ...options,
      stageId: this.connectionId,
    });
    // Deliver via transport if available
    if (this.maestro.httpTransport) {
      await this.maestro.httpTransport.send(message).catch((err: unknown) => {
        console.error('[ConnectionHandle] Transport broadcast error:', err);
      });
    }
    return message;
  }

  /** Report to supervisor (hierarchy Connections) */
  async reportTo(content: string, options: SendOptions = {}): Promise<MaestroMessage> {
    this.requirePermission('message:send');
    const connection = this.getConnection();
    const supervisor = this.manager.getSupervisor(connection, this.maestro.agentId);
    if (!supervisor) throw new Error('No supervisor in this Connection.');
    return this.maestro.router.buildMessage('report', content, supervisor.agentId, {
      ...options,
      stageId: this.connectionId,
    });
  }

  /** Assign work to a subordinate (hierarchy Connections) */
  async assignTo(subordinateId: string, content: string, options: SendOptions = {}): Promise<MaestroMessage> {
    this.requirePermission('message:send');
    return this.maestro.router.buildMessage('assign', content, subordinateId, {
      ...options,
      stageId: this.connectionId,
    });
  }

  // ----------------------------------------------------------
  // Message handling
  // ----------------------------------------------------------

  /** Register a handler for messages in this Connection */
  on(type: MessageType | '*', handler: MessageHandler): void {
    this.maestro.router.on(type, (msg) => {
      if (msg.stageId === this.connectionId) handler(msg);
    });
  }

  // ----------------------------------------------------------
  // Member management
  // ----------------------------------------------------------

  getMembers(): ConnectionMember[] {
    return this.manager.visibleMembers(this.getConnection(), this.maestro.agentId);
  }

  getMember(agentId: string): ConnectionMember | undefined {
    return this.manager.getMember(this.connectionId, agentId);
  }

  assignRole(targetAgentId: string, role: string): void {
    this.manager.assignRole(this.connectionId, this.maestro.agentId, targetAgentId, role);
  }

  removeMember(agentId: string): void {
    this.manager.removeMember(this.connectionId, this.maestro.agentId, agentId);
  }

  transferRole(role: string, toAgentId: string, reason?: string): void {
    this.manager.transferRole(this.connectionId, this.maestro.agentId, {
      role, to: toAgentId, reason,
    });
  }

  // ----------------------------------------------------------
  // Lifecycle
  // ----------------------------------------------------------

  /** Leave this Connection */
  async leave(): Promise<void> {
    this.manager.leave(this.connectionId, this.maestro.agentId);
    this._onRemove();
  }

  /** Close this Connection (lead/host only) */
  async close(): Promise<void> {
    this.manager.close(this.connectionId, this.maestro.agentId);
    this._onRemove();
  }

  // ----------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------

  getConnectionInfo(): Connection {
    return this.getConnection();
  }

  private getConnection(): Connection {
    const c = this.manager.get(this.connectionId);
    if (!c) throw new Error(`Connection ${this.connectionId} not found`);
    return c;
  }

  private requirePermission(permission: Permission): void {
    this.manager.requirePermission(this.connectionId, this.maestro.agentId, permission);
  }
}

// ----------------------------------------------------------
// Maestro SDK
// ----------------------------------------------------------

export class Maestro {
  readonly agentId: string;
  readonly connectionManager: ConnectionManager;
  readonly router: MessageRouter;

  private config: MaestroConfig;
  private connectionHandles = new Map<string, ConnectionHandle>();
  private blackboards = new Map<string, SharedBlackboard>();
  private started = false;
  /** @internal exposed for ConnectionHandle delivery */
  httpTransport: HttpTransport | null = null;
  /** @internal exposed for ConnectionHandle BB notifications */
  blackboardBridge: BlackboardBridge | null = null;
  private openclawAdapter: OpenClawAdapter | null = null;
  private registry: LocalRegistry | null = null;
  private mdnsDiscovery: MdnsDiscovery | null = null;
  private connectionBroker: ConnectionBroker | null = null;
  private connectionStore: ConnectionStore | null = null;

  constructor(config: MaestroConfig) {
    this.config = config;
    this.agentId = config.agentId;
    this.connectionManager = new ConnectionManager();
    this.router = new MessageRouter(config.agentId, this.connectionManager);
  }

  // ----------------------------------------------------------
  // Lifecycle
  // ----------------------------------------------------------

  async start(): Promise<void> {
    if (this.started) return;
    this.started = true;

    // Boot HttpTransport if transport config is present
    if (this.config.transport) {
      const port = this.config.transport.port ?? 3842;
      const registryPath = this.config.transport.registryPath ?? '.maestro/registry.json';
      this.registry = new LocalRegistry(registryPath);

      // Optionally wire OpenClaw adapter
      let openclawWebhook: string | undefined;
      let openclawToken: string | undefined;
      if (this.config.openclaw) {
        openclawWebhook = this.config.openclaw.gatewayUrl;
        openclawToken = this.config.openclaw.hookToken;
        this.openclawAdapter = new OpenClawAdapter({
          gatewayUrl: this.config.openclaw.gatewayUrl,
          hookToken: this.config.openclaw.hookToken,
          agentSessions: this.config.openclaw.agentSessions,
        });
      }

      this.httpTransport = new HttpTransport(
        this.agentId,
        this.router,
        this.registry,
        { port, registryPath, openclawWebhook, openclawToken },
        this.connectionManager,
      );
      await this.httpTransport.start();

      // Boot ConnectionBroker and ConnectionStore
      this.connectionStore = new ConnectionStore(
        this.config.transport.dbPath ?? '.maestro/connections.db',
      );
      this.connectionBroker = new ConnectionBroker(
        this.agentId,
        this.httpTransport,
        this.registry,
        this.connectionManager,
        { localPort: port },
      );

      // Wire BlackboardBridge for cross-process push
      this.blackboardBridge = new BlackboardBridge(
        this.agentId,
        this.httpTransport,
        this.registry,
      );

      // Boot mDNS discovery if configured
      if (this.config.discovery?.method === 'mdns') {
        this.mdnsDiscovery = new MdnsDiscovery(
          { agentId: this.agentId, port },
          this.registry,
        );
        await this.mdnsDiscovery.advertise();
        await this.mdnsDiscovery.browse();
      }
    } else if (this.config.openclaw) {
      // OpenClaw adapter without HTTP transport
      this.openclawAdapter = new OpenClawAdapter({
        gatewayUrl: this.config.openclaw.gatewayUrl,
        hookToken: this.config.openclaw.hookToken,
        agentSessions: this.config.openclaw.agentSessions,
      });
    }
  }

  async stop(): Promise<void> {
    if (this.mdnsDiscovery) {
      await this.mdnsDiscovery.stop();
      this.mdnsDiscovery = null;
    }
    if (this.httpTransport) {
      await this.httpTransport.stop();
      this.httpTransport = null;
    }
    this.connectionBroker = null;
    this.connectionStore = null;
    this.started = false;
  }

  // ----------------------------------------------------------
  // Connection Management
  // ----------------------------------------------------------

  /** Create a new Connection and return a handle to it */
  createConnection(request: CreateConnectionRequest): ConnectionHandle {
    const connection = this.connectionManager.create(request, this.agentId);
    return this.makeHandle(connection.id);
  }

  /**
   * Create a Connection with sensible defaults (open, no hierarchy).
   * Shortcut for common "open peer" setups.
   */
  openConnection(name: string): ConnectionHandle {
    return this.createConnection({
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

  openHierarchicalConnection(
    name: string,
    roles: string[],
    reportingChain: Record<string, string>,
  ): ConnectionHandle {
    const permissions: Record<string, Permission[]> = {};
    // Top role gets full permissions, others get progressively fewer
    roles.forEach((role, i) => {
      if (i === 0) {
        permissions[role] = [...DEFAULT_PERMISSIONS.lead];
      } else {
        permissions[role] = [...DEFAULT_PERMISSIONS.worker];
      }
    });

    return this.createConnection({
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
   * Join an existing Connection by ID.
   *
   * In local mode (same process), pass the host's ConnectionManager so this
   * agent's join request is processed against the correct Connection store.
   * In network mode, the join request is sent over HTTP to the host.
   *
   * @param connectionId  The Connection to join
   * @param hostManager   The ConnectionManager that owns the Connection (local mode)
   * @param options       Additional join options
   */
  join(
    connectionId: string,
    hostManager?: ConnectionManager,
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

    // Use the provided host ConnectionManager (local mode), or own (self-join / network mode)
    const manager = hostManager ?? this.connectionManager;
    const response = manager.processJoin(connectionId, request);

    if (response.status === 'accepted') {
      // Mirror the connection into this agent's manager so it can enforce permissions locally
      if (hostManager) {
        const connection = hostManager.get(connectionId);
        if (connection) {
          // Store reference - use the host's ConnectionManager for all connection ops
          this._sharedManagers.set(connectionId, hostManager);
        }
      }
      this.makeHandle(connectionId, hostManager);
    }

    return response;
  }

  /** @internal Shared ConnectionManager references for locally-joined Connections */
  private _sharedManagers = new Map<string, ConnectionManager>();

  /** @internal Get the authoritative ConnectionManager for a Connection */
  getManagerForConnection(connectionId: string): ConnectionManager {
    return this._sharedManagers.get(connectionId) ?? this.connectionManager;
  }

  getConnection(connectionId: string): ConnectionHandle | undefined {
    return this.connectionHandles.get(connectionId);
  }

  listConnections(): ConnectionHandle[] {
    return [...this.connectionHandles.values()];
  }

  /** List all persisted Connections (active and closed). */
  listStoredConnections(): StoredConnection[] {
    return this.connectionStore?.list() ?? [];
  }

  // ----------------------------------------------------------
  // Message Routing (global)
  // ----------------------------------------------------------

  /** Register a global message handler (all Connections) */
  onMessage(type: MessageType | '*', handler: MessageHandler): void {
    this.router.on(type, handler);
  }

  /** Dispatch an inbound message (called by webhook receiver) */
  async receive(message: MaestroMessage): Promise<{ accepted: boolean; reason?: string }> {
    return this.router.dispatch(message);
  }

  // ----------------------------------------------------------
  // Network Connection Management
  // ----------------------------------------------------------

  /**
   * Create a Connection (network-aware) and invite the specified agents.
   * Requires HTTP transport to be running.
   */
  async openConnectionWith(options: {
    name: string;
    members: string[];
    entryMode?: import('../connection/types.js').EntryMode;
    hierarchy?: import('../connection/types.js').ConnectionHierarchy;
    expiresAt?: number;
  }): Promise<ConnectionHandle> {
    if (!this.connectionBroker) {
      throw new Error('ConnectionBroker not available - start with transport config first');
    }
    const { connectionId } = await this.connectionBroker.createConnection(options);
    return this.makeHandle(connectionId);
  }

  /**
   * Join a remote Connection by connectionId.
   * Returns a ConnectionHandle on success, null on failure.
   */
  async joinConnection(hostAgentId: string, connectionId: string): Promise<ConnectionHandle | null> {
    if (!this.connectionBroker) {
      return null;
    }
    const response = await this.connectionBroker.joinRemote({ hostAgentId, connectionId });
    if (response.status !== 'accepted') {
      return null;
    }
    // Mirror the remote Connection into our local ConnectionManager so that
    // getMembers(), permission checks, etc. work correctly on this side.
    if (response.rules && response.members) {
      this.connectionManager.mirrorConnection(
        connectionId,
        response.name ?? connectionId,
        response.hostAgentId ?? hostAgentId,
        response.rules,
        response.members,
      );
    }
    // Persist the connection
    if (this.connectionStore && this.registry) {
      const reg = this.registry.lookup(hostAgentId);
      const hostEndpoint = reg
        ? reg.webhookEndpoint.replace(/\/[^/]+$/, '')
        : '';
      this.connectionStore.save({
        connectionId,
        name:         connectionId,
        hostAgentId,
        hostEndpoint,
        myRole:       response.role ?? 'worker',
        status:       'active',
        joinedAt:     Date.now(),
      });
    }
    return this.makeHandle(connectionId);
  }

  /**
   * Accept a connection:invitation message by joining the remote Connection.
   */
  async acceptInvitation(invitation: ConnectionInvitation): Promise<ConnectionHandle | null> {
    if (!this.connectionBroker) {
      return null;
    }
    const response = await this.connectionBroker.acceptInvitation(invitation);
    if (response.status !== 'accepted') {
      return null;
    }
    if (this.connectionStore) {
      this.connectionStore.save({
        connectionId:  invitation.connectionId,
        name:          invitation.connectionName,
        hostAgentId:   invitation.hostAgentId,
        hostEndpoint:  invitation.hostEndpoint,
        myRole:        response.role ?? 'worker',
        status:        'active',
        joinedAt:      Date.now(),
      });
    }
    return this.makeHandle(invitation.connectionId);
  }

  /**
   * Send a direct message to an agent by ID.
   * Looks up the recipient in the local registry and delivers via HTTP transport.
   */
  async sendDirect(recipientId: string, content: string): Promise<{ ok: boolean; error?: string }> {
    if (!this.httpTransport) {
      return { ok: false, error: 'HTTP transport not running (no transport config)' };
    }
    const message = this.router.buildMessage('direct', content, recipientId);
    return this.httpTransport.send(message);
  }

  // ----------------------------------------------------------
  // Internal
  // ----------------------------------------------------------

  private makeHandle(connectionId: string, hostManager?: ConnectionManager): ConnectionHandle {
    if (!this.blackboards.has(connectionId)) {
      let bb: SharedBlackboard;
      if (this.config.transport) {
        // Persistent SQLite blackboard for cross-process scenarios
        const dbPath = this.config.transport.dbPath ?? '.maestro/blackboard.db';
        const sqliteBb = new SQLiteBlackboard(connectionId, dbPath);
        bb = sqliteBb;
        // Register with transport so incoming updates are applied
        if (this.httpTransport) {
          this.httpTransport.registerBlackboard(connectionId, sqliteBb);
        }
      } else {
        // In-process / test mode
        bb = new InMemoryBlackboard();
      }
      this.blackboards.set(connectionId, bb);
    }
    const bb = this.blackboards.get(connectionId)!;
    const handle = new ConnectionHandle(this, connectionId, bb, hostManager, () => this.removeConnectionHandle(connectionId));
    this.connectionHandles.set(connectionId, handle);
    return handle;
  }

  private removeConnectionHandle(connectionId: string): void {
    this.connectionHandles.delete(connectionId);
  }

  getBlackboard(connectionId: string): SharedBlackboard | undefined {
    return this.blackboards.get(connectionId);
  }
}
