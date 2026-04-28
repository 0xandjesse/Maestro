// ============================================================
// Maestro Protocol — Blackboard Bridge
// ============================================================
//
// Cross-process push layer. When a local agent writes to the
// blackboard, the bridge fans out a `blackboard:update` message
// to all other known members of the connection via the HTTP
// transport.
//
// Delivery is best-effort (fire-and-forget). Errors are logged
// but never thrown — a failed notification is recoverable on
// the next poll; don't crash the writer for it.
// ============================================================

import { randomUUID } from 'crypto';
import { BlackboardEntry } from './types.js';
import { HttpTransport } from '../transport/HttpTransport.js';
import { LocalRegistry } from '../transport/LocalRegistry.js';
import { MaestroMessage } from '../types/index.js';

export class BlackboardBridge {
  constructor(
    private agentId: string,
    private transport: HttpTransport,
    private registry: LocalRegistry,
  ) {}

  /**
   * Fan out a blackboard:update message to the specified recipients.
   * Called after any local BB write (set or delete).
   *
   * @param stageId     Stage namespace for the BB entry
   * @param entry       The entry that was written (value=undefined for deletes)
   * @param recipients  agentIds to notify (typically all other Stage members)
   */
  async notifyUpdate(
    stageId: string,
    entry: BlackboardEntry,
    recipients: string[],
  ): Promise<void> {
    if (recipients.length === 0) return;

    const payload = {
      stageId,
      key: entry.key,
      value: entry.value,
      writtenBy: entry.writtenBy,
      writtenAt: entry.writtenAt,
      version: entry.version,
      deleted: entry.value === undefined,
    };

    const promises = recipients
      .filter(id => id !== this.agentId) // Never notify self
      .map(async (recipientId) => {
        const registration = this.registry.lookup(recipientId);
        if (!registration) {
          console.warn(`[BlackboardBridge] Recipient ${recipientId} not in registry — skipping`);
          return;
        }

        const message: MaestroMessage = {
          id: randomUUID(),
          type: 'blackboard:update',
          content: entry.key,
          sender: { agentId: this.agentId },
          recipient: recipientId,
          timestamp: Date.now(),
          stageId,
          version: '3.2',
          payload,
        };

        try {
          const result = await this.transport.send(message);
          if (!result.ok) {
            console.warn(`[BlackboardBridge] Delivery to ${recipientId} failed: ${result.error}`);
          }
        } catch (err) {
          console.error(`[BlackboardBridge] Unexpected error notifying ${recipientId}:`, err);
        }
      });

    // Fire and forget — all errors are caught inside the map
    await Promise.allSettled(promises);
  }
}
