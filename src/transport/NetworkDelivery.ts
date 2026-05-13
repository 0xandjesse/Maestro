// ============================================================
// Maestro Protocol — Network Delivery
// ============================================================
//
// Outbound HTTP delivery with 1 retry, 100-250ms backoff,
// ≤5s total timeout per spec.
// Uses Node 24 native fetch — no dependencies.
// ============================================================

import { MaestroMessage } from '../types/index.js';

export interface DeliveryResult {
  ok: boolean;
  statusCode?: number;
  error?: string;
}

const DEFAULT_TIMEOUT_MS = 5000;

function randomBackoff(): number {
  return 100 + Math.floor(Math.random() * 151); // 100-250ms
}

async function fetchWithTimeout(
  endpoint: string,
  body: string,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Deliver a MaestroMessage to a remote agent endpoint via HTTP POST.
 * Retries once on failure with a random 100-250ms backoff.
 * Total time budget: ≤5s.
 */
export async function deliverMessage(
  endpoint: string,
  message: MaestroMessage,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<DeliveryResult> {
  const body = JSON.stringify(message);
  // Reserve backoff time from the budget for the second attempt
  const perAttemptMs = Math.floor((timeoutMs - 250) / 2);

  let lastError: string | undefined;
  let lastStatus: number | undefined;

  for (let attempt = 0; attempt < 2; attempt++) {
    if (attempt > 0) {
      await new Promise(r => setTimeout(r, randomBackoff()));
    }
    try {
      const res = await fetchWithTimeout(endpoint, body, Math.max(perAttemptMs, 1000));
      lastStatus = res.status;
      if (res.ok) {
        return { ok: true, statusCode: res.status };
      }
      lastError = `HTTP ${res.status}`;
    } catch (err: unknown) {
      lastError = err instanceof Error ? err.message : String(err);
    }
  }

  return { ok: false, statusCode: lastStatus, error: lastError };
}

// Named export for namespace-style usage
export const NetworkDelivery = { deliverMessage };
