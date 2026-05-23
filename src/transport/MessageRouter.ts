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
  private venueHandlers = new Map<string, Map<string, Set<MessageHandler>>>();
  private connectionManager: ConnectionManager;
  private agentId: string;
  private wallet: string | undefined;

  constructor(agentId: string, connectionManager: ConnectionManager, wallet?: string) {
    super();
    this.agentId = agentId;
    this.wallet = wallet;
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

  /**
   * Register a handler scoped to a specific Venue/Connection.
   * Only receives messages whose venueId matches.
   */
  onVenue(venueId: string, type: MessageType | '*', handler: MessageHandler): this {
    if (!this.venueHandlers.has(venueId)) {
      this.venueHandlers.set(venueId, new Map());
    }
    const venueMap = this.venueHandlers.get(venueId)!;
    const key = String(type);
    if (!venueMap.has(key)) {
      venueMap.set(key, new Set());
    }
    venueMap.get(key)!.add(handler);
    return this;
  }

  offVenue(venueId: string, type: MessageType | '*', handler: MessageHandler): this {
    const venueMap = this.venueHandlers.get(venueId);
    if (venueMap) {
      venueMap.get(String(type))?.delete(handler);
    }
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

    let all: MessageHandler[] = [];

    if (message.venueId) {
      // Scoped to a specific venue: only deliver to venue-specific handlers
      const venueMap = this.venueHandlers.get(message.venueId);
      if (venueMap) {
        const typeHandlers = venueMap.get(message.type) ?? new Set();
        const wildcardHandlers = venueMap.get('*') ?? new Set();
        all = [...typeHandlers, ...wildcardHandlers];
      }
      // If no venue-specific handlers registered, fall through to global handlers
      // to maintain backward compatibility for agents that haven't adopted per-venue handlers
      if (all.length === 0) {
        const typeHandlers = this.handlers.get(message.type) ?? new Set();
        const wildcardHandlers = this.handlers.get('*') ?? new Set();
        all = [...typeHandlers, ...wildcardHandlers];
      }
    } else {
      // No venueId: messages must explicitly opt in to broadcast delivery.
      // Previously, messages without a venueId would fan out to ALL global
      // handlers, causing duplicate delivery for direct messages.
      //
      // CL-proteus-5d568a80 Item B: Require explicit broadcast:true flag or
      // venue list.  Messages without a venueId that lack broadcast:true are
      // treated as point-to-point and only delivered to type-specific handlers.
      // Ambiguous messages (no venue, no broadcast flag, not type='broadcast')
      // are logged as broadcast_blocked_no_scope for forensic tracing.

      const isExplicitBroadcast = (message as any).broadcast === true;
      const isTypeBroadcast = message.type === 'broadcast';
      const isWildcardRecipient = message.recipient === '*';

      if (isExplicitBroadcast || isTypeBroadcast || isWildcardRecipient) {
        // Legitimate broadcast — fan out to all global handlers
        const typeHandlers = this.handlers.get(message.type) ?? new Set();
        const wildcardHandlers = this.handlers.get('*') ?? new Set();
        all = [...typeHandlers, ...wildcardHandlers];
      } else {
        // Point-to-point without venueId and without explicit broadcast flag:
        // deliver only to type-specific handlers (not wildcards).
        // Log the suppression for forensic tracing.
        all = [...(this.handlers.get(message.type) ?? new Set())];

        // Emit broadcast_blocked_no_scope event for forensic tracing
        this.emit('broadcast_blocked_no_scope', {
          messageId: message.id,
          type: message.type,
          recipient: message.recipient,
          reason: 'no venueId and no explicit broadcast:true flag',
        });
      }
    }

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
    options: SendOptions & { stageId?: string; provenance?: MaestroMessage['provenance']; broadcast?: boolean } = {},
  ): MaestroMessage {
    return {
      id: randomUUID(),
      type,
      content,
      sender: { agentId: this.agentId, wallet: this.wallet },
      recipient,
      timestamp: Date.now(),
      version: PROTOCOL_VERSION,
      ...(options.stageId ? { stageId: options.stageId } : {}),
      ...(options.venueId ? { venueId: options.venueId } : {}),
      ...(options.replyTo ? { replyTo: options.replyTo } : {}),
      ...(options.provenance ? { provenance: options.provenance } : {}),
      ...(options.broadcast ? { broadcast: options.broadcast } : {}),
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
