// ============================================================
// Maestro Protocol — Network Transport
// ============================================================
//
// Delivers messages to remote agents via HTTP POST.
// Spec: 1 retry, 100-250ms backoff, ≤5s total per message.
//
// Used when the recipient agent is in a different process.
// For same-process delivery, use MessageRouter.deliverLocal().
// ============================================================

import { MaestroMessage } from '../types/index.js';
import { AgentRegistration } from './types.js';

export interface DeliveryResult {
  success: boolean;
  statusCode?: number;
  reason?: string;
  attempts: number;
}

export interface NetworkTransportOptions {
  /** Max ms to spend on a single delivery (all retries). Default: 5000 */
  timeoutMs?: number;
  /** Backoff before retry, in ms. Default: random 100-250 */
  retryDelayMs?: () => number;
  /** Max retries. Spec says 1. Default: 1 */
  maxRetries?: number;
}

export class NetworkTransport {
  private timeoutMs: number;
  private retryDelayMs: () => number;
  private maxRetries: number;

  constructor(options: NetworkTransportOptions = {}) {
    this.timeoutMs = options.timeoutMs ?? 5_000;
    this.retryDelayMs = options.retryDelayMs ?? (() => 100 + Math.random() * 150);
    this.maxRetries = options.maxRetries ?? 1;
  }

  // ----------------------------------------------------------
  // Delivery
  // ----------------------------------------------------------

  /**
   * Send a message to a remote agent's webhook endpoint.
   * Looks up the recipient in the registry, then POSTs.
   */
  async send(
    message: MaestroMessage,
    recipientEndpoint: string,
  ): Promise<DeliveryResult> {
    const deadline = Date.now() + this.timeoutMs;
    let lastError: string | undefined;
    let attempts = 0;

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      if (Date.now() >= deadline) break;
      attempts++;

      try {
        const remaining = deadline - Date.now();
        const result = await this.postWithTimeout(recipientEndpoint, message, remaining);

        if (result.ok || result.statusCode === 422) {
          // 422 = message rejected by policy (not a transport error — don't retry)
          return {
            success: result.ok,
            statusCode: result.statusCode,
            reason: result.body?.reason,
            attempts,
          };
        }

        // 4xx (not 422) = client error, don't retry
        if (result.statusCode >= 400 && result.statusCode < 500) {
          return {
            success: false,
            statusCode: result.statusCode,
            reason: `client_error_${result.statusCode}`,
            attempts,
          };
        }

        // 5xx or network error — retry
        lastError = `http_${result.statusCode}`;
      } catch (err) {
        lastError = String(err);
      }

      // Wait before retry (if not last attempt)
      if (attempt < this.maxRetries && Date.now() < deadline) {
        await sleep(this.retryDelayMs());
      }
    }

    return {
      success: false,
      reason: lastError ?? 'timeout',
      attempts,
    };
  }

  /**
   * Broadcast a message to multiple agents.
   * Returns per-agent delivery results.
   */
  async broadcast(
    message: MaestroMessage,
    recipients: AgentRegistration[],
  ): Promise<Map<string, DeliveryResult>> {
    const results = new Map<string, DeliveryResult>();

    await Promise.all(
      recipients.map(async (agent) => {
        const result = await this.send(message, agent.webhookEndpoint);
        results.set(agent.agentId, result);
      }),
    );

    return results;
  }

  // ----------------------------------------------------------
  // Internal
  // ----------------------------------------------------------

  private async postWithTimeout(
    url: string,
    body: MaestroMessage,
    timeoutMs: number,
  ): Promise<{ ok: boolean; statusCode: number; body?: { accepted?: boolean; reason?: string } }> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      let parsed: { accepted?: boolean; reason?: string } | undefined;
      try {
        parsed = await response.json() as { accepted?: boolean; reason?: string };
      } catch {
        // Non-JSON body — ignore
      }

      return {
        ok: response.ok,
        statusCode: response.status,
        body: parsed,
      };
    } catch (err) {
      // AbortError = timeout, or network failure
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
