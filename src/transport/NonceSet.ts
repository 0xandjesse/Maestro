// ============================================================
// Maestro Protocol — NonceSet (Replay Protection)
// ============================================================
//
// Dedup + timestamp drift checking for inbound messages.
//
// Enforces:
//   - |now - timestamp| <= maxDriftMs
//   - nonce has not been seen before
//
// System messages are exempt from drift checks (network latency tolerant).
//
// Ported from Python maestro_transport.py -> TypeScript (May 2026)
// ============================================================

import { randomUUID } from 'crypto';

export interface NonceCheckResult {
  ok: boolean;
  reason?: string;
}

export class NonceSet {
  private _seen = new Map<string, number>();
  private _ttlMs: number;
  private _maxSize: number;
  private _maxDriftMs: number;

  constructor(
    ttlSeconds = 300,
    maxSize = 10_000,
    maxDriftSec = 30,
  ) {
    this._ttlMs = ttlSeconds * 1_000;
    this._maxSize = maxSize;
    this._maxDriftMs = maxDriftSec * 1_000;
  }

  /** Check nonce + timestamp; returns {ok, reason?}. Records nonce on success. */
  check(nonce: string | number | null | undefined, timestamp: string | number | null | undefined, msgType = 'direct'): NonceCheckResult {
    const now = Date.now();
    const key = nonce ? String(nonce) : '';

    if (!key) {
      return { ok: false, reason: 'missing nonce' };
    }

    // Parse timestamp
    let tsMs = 0;
    if (timestamp != null) {
      if (typeof timestamp === 'number') {
        tsMs = timestamp;
      } else      if (typeof timestamp === 'string') {
        const dt = new Date(timestamp.trim());
        tsMs = dt.getTime();
        if (Number.isNaN(tsMs)) {
          return { ok: false, reason: `invalid timestamp format: ${timestamp}` };
        }
      } else {
        tsMs = Number(timestamp);
      }
    }

    // Drift check (system exempt)
    if (msgType !== 'system' && tsMs) {
      const drift = Math.abs(now - tsMs);
      if (drift > this._maxDriftMs) {
        return { ok: false, reason: `timestamp drift ${drift}ms exceeds max ${this._maxDriftMs}ms` };
      }
    }

    // Expire old entries
    for (const [k, v] of this._seen) {
      if (now - v >= this._ttlMs) {
        this._seen.delete(k);
      }
    }

    // Duplicate check
    if (this._seen.has(key)) {
      return { ok: false, reason: 'duplicate nonce' };
    }

    // Prune if oversized (FIFO — oldest first)
    while (this._seen.size >= this._maxSize) {
      const oldest = this._seen.keys().next().value as string | undefined;
      if (oldest !== undefined) {
        this._seen.delete(oldest);
      } else {
        break;
      }
    }

    this._seen.set(key, now);
    return { ok: true };
  }

  /** Convenience alias: returns ok only */
  isDuplicate(nonce: string): boolean {
    const result = this.check(nonce, Date.now(), 'direct');
    return !result.ok;
  }

  /** Generate a new nonce */
  static makeNonce(): string {
    return randomUUID();
  }
}
