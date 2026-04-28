// ============================================================
// Maestro Protocol - HTTP Transport
// ============================================================
//
// Express server that:
//   POST /message  - receives inbound MaestroMessages from peers
//   POST /webhook  - receives outbound requests from OpenClaw tool calls
//   GET  /health   - liveness check
//
// On startup, registers this agent in the LocalRegistry so peers
// can discover its endpoint.
// ============================================================

import express, { Application, Request, Response } from 'express';
import { createServer, Server } from 'http';
import { randomUUID } from 'crypto';
import { MaestroMessage } from '../types/index.js';
import { MessageRouter } from './MessageRouter.js';
import { LocalRegistry } from './LocalRegistry.js';
import { deliverMessage } from './NetworkDelivery.js';
import { OpenClawAdapter, OpenClawAdapterConfig } from '../plugin/OpenClawAdapter.js';
import { SQLiteBlackboard } from '../blackboard/SQLiteBlackboard.js';
import { BlackboardEntry } from '../blackboard/types.js';
import { ConnectionManager } from '../connection/ConnectionManager.js';
import { JoinRequest, ConnectionEvent } from '../connection/types.js';

export interface HttpTransportConfig {
  port: number;
  host?: string;
  registryPath?: string;
  openclawWebhook?: string;
  openclawToken?: string;
}

export class HttpTransport {
  private app: Application;
  private server: Server | null = null;
  private startedAt: number | null = null;
  private openclawAdapter: OpenClawAdapter | null = null;
  private blackboards = new Map<string, SQLiteBlackboard>();

  constructor(
    private agentId: string,
    private router: MessageRouter,
    private registry: LocalRegistry,
    private config: HttpTransportConfig,
    private connectionManager?: ConnectionManager,   // optional - backwards compat
  ) {
    this.app = express();
    this.setupMiddleware();
    this.setupRoutes();

    // Optionally wire OpenClaw adapter if credentials provided
    if (config.openclawWebhook && config.openclawToken) {
      const adapterConfig: OpenClawAdapterConfig = {
        gatewayUrl: config.openclawWebhook,
        hookToken: config.openclawToken,
      };
      this.openclawAdapter = new OpenClawAdapter(adapterConfig);
    }
  }

  // ----------------------------------------------------------
  // Lifecycle
  // ----------------------------------------------------------

  async start(): Promise<void> {
    return new Promise((resolve, reject) => {
      const host = this.config.host ?? '0.0.0.0';
      const port = this.config.port;

      this.server = createServer(this.app);
      this.server.listen(port, host, () => {
        this.startedAt = Date.now();
        const endpoint = `http://${host === '0.0.0.0' ? '127.0.0.1' : host}:${port}`;
        // Register in the local registry
        this.registry.register({
          agentId: this.agentId,
          webhookEndpoint: `${endpoint}/message`,
        });
        console.log(`[HttpTransport] ${this.agentId} listening on ${endpoint}`);
        resolve();
      });
      this.server.on('error', reject);
    });
  }

  async stop(): Promise<void> {
    this.registry.unregister(this.agentId);
    return new Promise((resolve) => {
      if (!this.server) return resolve();
      this.server.close(() => {
        this.server = null;
        this.startedAt = null;
        resolve();
      });
    });
  }

  // ----------------------------------------------------------
  // Blackboard registration
  // ----------------------------------------------------------

  /**
   * Register a SQLiteBlackboard for a stage so incoming
   * blackboard:update messages can be applied locally.
   */
  registerBlackboard(stageId: string, bb: SQLiteBlackboard): void {
    this.blackboards.set(stageId, bb);
  }

  // ----------------------------------------------------------
  // Outbound
  // ----------------------------------------------------------

  /** Send a message to a remote agent (looks up endpoint from registry) */
  async send(message: MaestroMessage): Promise<{ ok: boolean; error?: string }> {
    const recipientId = message.recipient;
    if (!recipientId || recipientId === '*') {
      // Broadcast: send to all registered agents except self
      const all = this.registry.listActive();
      const peers = all.filter(a => a.agentId !== this.agentId);
      const results = await Promise.all(
        peers.map(peer => deliverMessage(peer.webhookEndpoint, message)),
      );
      const failed = results.filter(r => !r.ok);
      if (failed.length === 0) return { ok: true };
      return { ok: false, error: `${failed.length}/${peers.length} deliveries failed` };
    }

    const registration = this.registry.lookup(recipientId);
    if (!registration) {
      return { ok: false, error: `Agent '${recipientId}' not found in registry` };
    }
    const result = await deliverMessage(registration.webhookEndpoint, message);
    return { ok: result.ok, error: result.error };
  }

  // ----------------------------------------------------------
  // Express setup
  // ----------------------------------------------------------

  private setupMiddleware(): void {
    this.app.use(express.json({ limit: '1mb' }));
  }

  private setupRoutes(): void {
    // ----- POST /message - inbound from remote peers -----
    this.app.post('/message', async (req: Request, res: Response) => {
      const message = req.body as MaestroMessage;

      if (!message || !message.id || !message.type || !message.sender) {
        res.status(400).json({ accepted: false, reason: 'Invalid message format' });
        return;
      }

      try {
        const result = await this.router.dispatch(message);

        if (!result.accepted) {
          res.status(422).json({ accepted: false, reason: result.reason });
          return;
        }

        // Handle blackboard:update - apply to local SQLiteBlackboard
        if (message.type === 'blackboard:update') {
          this.applyBlackboardUpdate(message);
        }

        // Wake OpenClaw agent session if adapter is configured
        if (this.openclawAdapter) {
          // Don't await - fire and forget
          this.openclawAdapter.wakeAgent(this.agentId, message).catch((err: unknown) => {
            console.error('[HttpTransport] OpenClaw wake failed:', err);
          });
        }

        res.status(200).json({ accepted: true });
      } catch (err: unknown) {
        console.error('[HttpTransport] Dispatch error:', err);
        res.status(500).json({ accepted: false, reason: 'Internal error' });
      }
    });

    // ----- POST /webhook - inbound from OpenClaw tool (maestro_send) -----
    this.app.post('/webhook', async (req: Request, res: Response) => {
      // OpenClaw sends a MaestroMessage here when an agent calls maestro_send
      const message = req.body as MaestroMessage;

      if (!message || !message.id || !message.type) {
        res.status(400).json({ ok: false, reason: 'Invalid webhook payload' });
        return;
      }

      try {
        // If recipient is local, dispatch directly
        if (message.recipient === this.agentId || message.recipient === '*') {
          await this.router.dispatch(message);
          res.status(200).json({ ok: true, routed: 'local' });
          return;
        }

        // Otherwise forward to the correct remote agent
        const result = await this.send(message);
        res.status(result.ok ? 200 : 502).json({ ok: result.ok, error: result.error });
      } catch (err: unknown) {
        console.error('[HttpTransport] Webhook error:', err);
        res.status(500).json({ ok: false, reason: 'Internal error' });
      }
    });

    // ----- GET /health -----
    this.app.get('/health', (_req: Request, res: Response) => {
      res.status(200).json({
        ok: true,
        agentId: this.agentId,
        uptime: this.startedAt ? Date.now() - this.startedAt : 0,
      });
    });

    // ----- Connection endpoints (only wired when ConnectionManager is provided) -----
    this.setupConnectionRoutes();
  }

  private setupConnectionRoutes(): void {
    // ----- GET /connections/:connectionId - get Connection info -----
    this.app.get('/connections/:connectionId', (req: Request, res: Response) => {
      if (!this.connectionManager) {
        res.status(503).json({ error: 'connection_manager_unavailable' });
        return;
      }
      const cid = req.params['connectionId'] as string;
      const connection = this.connectionManager.get(cid);
      if (!connection) {
        res.status(404).json({ error: 'not_found' });
        return;
      }
      // Return safe public subset - no internal member state
      res.json({
        id:     connection.id,
        name:   connection.name,
        status: connection.status,
        rules:  connection.rules,
      });
    });

    // ----- POST /connections/:connectionId/join - remote agent requests to join -----
    this.app.post('/connections/:connectionId/join', async (req: Request, res: Response) => {
      if (!this.connectionManager) {
        res.status(503).json({ status: 'rejected', reason: 'connection_manager_unavailable' });
        return;
      }

      const { connectionId } = req.params as { connectionId: string };
      const joinRequest = req.body as JoinRequest;

      if (!joinRequest.agentId || !joinRequest.webhookEndpoint) {
        res.status(400).json({ status: 'rejected', reason: 'missing_fields' });
        return;
      }

      const response = this.connectionManager.processJoin(connectionId, joinRequest);

      if (response.status === 'accepted') {
        // Register the remote agent so we can reach it later
        this.registry.register({
          agentId:         joinRequest.agentId,
          webhookEndpoint: joinRequest.webhookEndpoint,
          capabilities:    joinRequest.capabilities,
        });

        // Notify existing members (fire-and-forget)
        this.notifyMembersJoined(connectionId, joinRequest.agentId).catch(() => {});
      }

      const httpStatus =
        response.status === 'accepted' ? 200 :
        response.status === 'pending'  ? 202 :
        403;

      res.status(httpStatus).json(response);
    });

    // ----- POST /connections/:connectionId/events - lifecycle event from host -----
    this.app.post('/connections/:connectionId/events', async (req: Request, res: Response) => {
      const event = req.body as ConnectionEvent;

      // Wrap the event as a connection:announcement message and dispatch via router
      const announcement: MaestroMessage = {
        id:        event.eventId ?? randomUUID(),
        type:      'connection:announcement',
        content:   JSON.stringify(event),
        sender:    { agentId: event.payload?.['hostAgentId'] as string ?? 'unknown' },
        recipient: this.agentId,
        stageId:   event.connectionId ?? (req.params['connectionId'] as string),
        timestamp: event.timestamp ?? Date.now(),
        version:   '3.2',
      };

      await this.router.dispatch(announcement).catch((err: unknown) => {
        console.error('[HttpTransport] Event dispatch error:', err);
      });

      // Wake OpenClaw if configured
      if (this.openclawAdapter) {
        this.openclawAdapter.wakeAgent(this.agentId, announcement).catch(() => {});
      }

      res.json({ ok: true });
    });
  }

  // ----------------------------------------------------------
  // Connection notification helpers
  // ----------------------------------------------------------

  /**
   * Notify all existing Connection members that a new agent has joined.
   * Best-effort - ignores delivery failures.
   */
  private async notifyMembersJoined(connectionId: string, newMemberId: string): Promise<void> {
    if (!this.connectionManager) return;
    const connection = this.connectionManager.get(connectionId);
    if (!connection) return;

    const promises: Promise<void>[] = [];
    for (const member of connection.members) {
      if (member.agentId === newMemberId || member.agentId === this.agentId) continue;
      const msg: MaestroMessage = {
        id:        randomUUID(),
        type:      'connection:announcement',
        content:   `Agent ${newMemberId} has joined the Connection`,
        sender:    { agentId: this.agentId },
        recipient: member.agentId,
        stageId:   connectionId,
        timestamp: Date.now(),
        version:   '3.2',
      };
      promises.push(
        this.send(msg).then(() => {}).catch(() => {}),
      );
    }
    await Promise.all(promises);
  }

  // ----------------------------------------------------------
  // Blackboard update handling
  // ----------------------------------------------------------

  /**
   * Apply an incoming blackboard:update message to the local
   * SQLiteBlackboard for the relevant stage, if one is registered.
   * Last-write-wins: only applies if incoming version > local version.
   */
  private applyBlackboardUpdate(message: MaestroMessage): void {
    const stageId = message.stageId;
    if (!stageId) return;

    const bb = this.blackboards.get(stageId);
    if (!bb) return;

    const payload = message.payload as {
      key: string;
      value: unknown;
      writtenBy: string;
      writtenAt: number;
      version: number;
      deleted?: boolean;
    } | undefined;

    if (!payload) return;

    const entry: BlackboardEntry = {
      key: payload.key,
      value: payload.deleted ? undefined : payload.value,
      writtenBy: payload.writtenBy,
      writtenAt: payload.writtenAt,
      version: payload.version,
    };

    try {
      bb.applyRemoteUpdate(entry);
    } catch (err) {
      console.error('[HttpTransport] Failed to apply blackboard update:', err);
    }
  }
}
