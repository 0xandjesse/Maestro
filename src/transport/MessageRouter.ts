// ============================================================
// Maestro Protocol — Message Router
// ============================================================
//
// Routes outbound messages and dispatches inbound messages
// to registered handlers. In local mode, delivery is
// in-process. In network mode, the router POSTs to agent
// webhook endpoints.
//
// Transport is intentionally simple: the protocol doesn't
// care about delivery guarantees beyond best-effort + retry.
// Spec: 1 retry, 100-250ms backoff, ≤5s total.
// ============================================================

import { EventEmitter } from 'events';
import { randomUUID } from 'crypto';
import { MaestroMessage, MessageType } from '../types/index.js';
import { ConnectionManager } from '../connection/ConnectionManager.js';
import { enforceProvenancePolicy } from '../connection/provenanceEnforcer.js';
import { MessageHandler, SendOptions } from './types.js';

const PROTOCOL_VERSION = '3.2';

// ----------------------------------------------------------
// MessageRouter
// ----------------------------------------------------------

export class MessageRouter extends EventEmitter {
  private handlers = new Map<string, Set<MessageHandler>>();
  private connectionManager: ConnectionManager;
  private agentId: string;

  constructor(agentId: string, connectionManager: ConnectionManager) {
    super();
    this.agentId = agentId;
    this.connectionManager = connectionManager;
  }

  // ----------------------------------------------------------
  // Handler Registration
  // ----------------------------------------------------------

  /**
   * Register a handler for incoming messages.
   * @param type  Message type, or '*' for all
   */
  on(type: MessageType | '*', handler: MessageHandler): this;
  on(event: string | symbol, listener: (...args: unknown[]) => void): this;
  on(typeOrEvent: MessageType | '*' | string | symbol, handler: MessageHandler | ((...args: unknown[]) => void)): this {
    const key = String(typeOrEvent);
    if (!this.handlers.has(key)) {
      this.handlers.set(key, new Set());
    }
    this.handlers.get(key)!.add(handler as MessageHandler);
    return this;
  }

  off(type: MessageType | '*', handler: MessageHandler): this;
  off(event: string | symbol, listener: (...args: unknown[]) => void): this;
  off(typeOrEvent: MessageType | '*' | string | symbol, handler: MessageHandler | ((...args: unknown[]) => void)): this {
    const key = String(typeOrEvent);
    this.handlers.get(key)?.delete(handler as MessageHandler);
    return this;
  }

  // ----------------------------------------------------------
  // Inbound
  // ----------------------------------------------------------

  /**
   * Dispatch an incoming message to all registered handlers.
   * Enforces Venue provenance policy before dispatch.
   */
  async dispatch(message: MaestroMessage): Promise<{ accepted: boolean; reason?: string }> {
    // Check Connection provenance policy if applicable
    if (message.stageId) {
      const connection = this.connectionManager.get(message.stageId);
      if (connection?.rules.provenancePolicy) {
        const check = enforceProvenancePolicy(message, connection.rules.provenancePolicy);
        if (!check.accepted) {
          return { accepted: false, reason: check.reason };
        }
      }
    }

    // Dispatch to type-specific handlers
    const typeHandlers = this.handlers.get(message.type) ?? new Set();
    const wildcardHandlers = this.handlers.get('*') ?? new Set();

    const all = [...typeHandlers, ...wildcardHandlers];
    await Promise.all(all.map(h => h(message)));

    // Also emit as an EventEmitter event for venue.on() usage
    super.emit(message.type, message);
    super.emit('*', message);

    return { accepted: true };
  }

  // ----------------------------------------------------------
  // Outbound (local in-process delivery)
  // ----------------------------------------------------------

  /**
   * Build an outbound MaestroMessage and deliver it locally
   * (in-process — for use within a single runtime).
   *
   * Network delivery (HTTP POST to remote webhook) is handled
   * by the NetworkTransport layer, which wraps this.
   */
  buildMessage(
    type: MessageType,
    content: string,
    recipient: string,
    options: SendOptions & { stageId?: string; provenance?: MaestroMessage['provenance'] } = {},
  ): MaestroMessage {
    return {
      id: randomUUID(),
      type,
      content,
      sender: { agentId: this.agentId },
      recipient,
      timestamp: Date.now(),
      version: PROTOCOL_VERSION,
      ...(options.stageId ? { stageId: options.stageId } : {}),
      ...(options.replyTo ? { replyTo: options.replyTo } : {}),
      ...(options.provenance ? { provenance: options.provenance } : {}),
    };
  }

  /**
   * Deliver a message to a local handler (same process).
   * Returns false if no handlers found.
   */
  async deliverLocal(message: MaestroMessage): Promise<boolean> {
    const result = await this.dispatch(message);
    return result.accepted;
  }
}
