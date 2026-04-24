// ============================================================
// Maestro Protocol — Webhook HTTP Server
// ============================================================
//
// Listens for inbound messages and events from remote agents.
// Agents expose a webhook endpoint that other agents POST to.
//
// Spec: agents register their webhookEndpoint on join.
// Remote senders POST MaestroMessage JSON to that endpoint.
// ============================================================

import { createServer, IncomingMessage, ServerResponse, Server } from 'http';
import { MaestroMessage } from '../types/index.js';

export type InboundHandler = (message: MaestroMessage) => Promise<{ accepted: boolean; reason?: string }>;

export interface WebhookServerOptions {
  port: number;
  path?: string;           // Default: /maestro/webhook
  agentId: string;
  onMessage: InboundHandler;
}

export class WebhookServer {
  private server: Server;
  private port: number;
  private path: string;
  private agentId: string;
  private onMessage: InboundHandler;
  private started = false;

  constructor(options: WebhookServerOptions) {
    this.port = options.port;
    this.path = options.path ?? '/maestro/webhook';
    this.agentId = options.agentId;
    this.onMessage = options.onMessage;
    this.server = createServer((req, res) => this.handle(req, res));
  }

  // ----------------------------------------------------------
  // Lifecycle
  // ----------------------------------------------------------

  start(): Promise<void> {
    if (this.started) return Promise.resolve();
    return new Promise((resolve, reject) => {
      this.server.listen(this.port, () => {
        this.started = true;
        resolve();
      });
      this.server.once('error', reject);
    });
  }

  stop(): Promise<void> {
    if (!this.started) return Promise.resolve();
    return new Promise((resolve, reject) => {
      this.server.close((err) => {
        if (err) reject(err);
        else {
          this.started = false;
          resolve();
        }
      });
    });
  }

  get endpoint(): string {
    return `http://localhost:${this.port}${this.path}`;
  }

  // ----------------------------------------------------------
  // Request handling
  // ----------------------------------------------------------

  private async handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
    // Only accept POST to the webhook path
    if (req.method !== 'POST' || req.url !== this.path) {
      res.writeHead(404);
      res.end(JSON.stringify({ error: 'not_found' }));
      return;
    }

    // Collect body
    let body = '';
    req.on('data', (chunk: Buffer) => { body += chunk.toString(); });
    req.on('end', async () => {
      try {
        const message: MaestroMessage = JSON.parse(body);

        // Basic sanity check
        if (!message.id || !message.type || !message.sender?.agentId) {
          res.writeHead(400);
          res.end(JSON.stringify({ error: 'invalid_message' }));
          return;
        }

        const result = await this.onMessage(message);

        if (result.accepted) {
          res.writeHead(200);
          res.end(JSON.stringify({ accepted: true }));
        } else {
          res.writeHead(422);
          res.end(JSON.stringify({ accepted: false, reason: result.reason }));
        }
      } catch (err) {
        res.writeHead(400);
        res.end(JSON.stringify({ error: 'parse_error', detail: String(err) }));
      }
    });
  }
}
