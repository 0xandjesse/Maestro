// ============================================================
// NonceSet Tests
// ============================================================

import { describe, it, expect } from '@jest/globals';
import { NonceSet } from '../transport/NonceSet.js';

// ----------------------------------------------------------
// Basic dedup
// ----------------------------------------------------------

describe('NonceSet - basic dedup', () => {
  it('accepts a fresh nonce', () => {
    const ns = new NonceSet();
    const result = ns.check('nonce-1', Date.now());
    expect(result.ok).toBe(true);
    expect(result.reason).toBeUndefined();
  });

  it('rejects a duplicate nonce', () => {
    const ns = new NonceSet();
    const ts = Date.now();
    ns.check('nonce-1', ts);
    const result = ns.check('nonce-1', ts);
    expect(result.ok).toBe(false);
    expect(result.reason).toBe('duplicate nonce');
  });

  it('rejects a missing nonce', () => {
    const ns = new NonceSet();
    const result = ns.check(null, Date.now());
    expect(result.ok).toBe(false);
    expect(result.reason).toBe('missing nonce');
  });

  it('rejects an empty-string nonce', () => {
    const ns = new NonceSet();
    const result = ns.check('', Date.now());
    expect(result.ok).toBe(false);
    expect(result.reason).toBe('missing nonce');
  });
});

// ----------------------------------------------------------
// Timestamp drift
// ----------------------------------------------------------

describe('NonceSet - drift check', () => {
  it('accepts a nonce within drift window', () => {
    const ns = new NonceSet(300, 10000, 30); // 30s drift
    const ts = Date.now();
    const result = ns.check('nonce-1', ts);
    expect(result.ok).toBe(true);
  });

  it('rejects a nonce outside drift window', () => {
    const ns = new NonceSet(300, 10000, 1); // 1s drift
    const ts = Date.now() - 2000; // 2s old
    const result = ns.check('nonce-1', ts);
    expect(result.ok).toBe(false);
    expect(result.reason).toContain('timestamp drift');
  });

  it('allows zero drift for system messages', () => {
    const ns = new NonceSet(300, 10000, 1); // 1s drift
    const ts = Date.now() - 5000; // 5s old
    const result = ns.check('nonce-1', ts, 'system');
    expect(result.ok).toBe(true);
  });
});

// ----------------------------------------------------------
// Timestamp parsing
// ----------------------------------------------------------

describe('NonceSet - timestamp formats', () => {
  it('accepts numeric timestamp', () => {
    const ns = new NonceSet();
    const ts = Date.now();
    const result = ns.check('nonce-1', ts);
    expect(result.ok).toBe(true);
  });

  it('accepts ISO-8601 string timestamp', () => {
    const ns = new NonceSet();
    const ts = new Date().toISOString();
    const result = ns.check('nonce-1', ts);
    expect(result.ok).toBe(true);
  });

  it('accepts ISO-8601 without trailing Z', () => {
    const ns = new NonceSet();
    const ts = new Date().toISOString().replace('Z', '+00:00');
    const result = ns.check('nonce-1', ts);
    expect(result.ok).toBe(true);
  });

  it('rejects invalid timestamp string', () => {
    const ns = new NonceSet();
    const result = ns.check('nonce-1', 'not-a-date');
    expect(result.ok).toBe(false);
    expect(result.reason).toContain('invalid timestamp');
  });
});

// ----------------------------------------------------------
// TTL expiration
// ----------------------------------------------------------

describe('NonceSet - TTL expiration', () => {
  it('accepts a previously seen nonce after TTL expires', () => {
    const ns = new NonceSet(0); // TTL = 0s
    const ts = Date.now();
    ns.check('nonce-old', ts);
    const result = ns.check('nonce-old', ts);
    expect(result.ok).toBe(true);
    expect(result.reason).toBeUndefined();
  });
});

// ----------------------------------------------------------
// Size limit / pruning
// ----------------------------------------------------------

describe('NonceSet - size limit', () => {
  it('prunes oldest entries when maxSize exceeded', () => {
    const ns = new NonceSet(300, 3); // max size 3
    ns.check('a', Date.now());
    ns.check('b', Date.now());
    ns.check('c', Date.now());
    ns.check('d', Date.now()); // evicts 'a'

    const replayA = ns.check('a', Date.now());
    expect(replayA.ok).toBe(true); // pruned, accepted as fresh
  });

  it('rejects still-present entries after pruning', () => {
    const ns = new NonceSet(300, 2); // max size 2
    ns.check('a', Date.now());
    ns.check('b', Date.now());

    // Adding 'c' evicts oldest 'a'
    ns.check('c', Date.now());

    // 'b' is still present, must reject first (check itself prunes)
    expect(ns.check('b', Date.now()).ok).toBe(false);
    // 'a' was pruned, can be re-accepted
    expect(ns.check('a', Date.now()).ok).toBe(true);
  });
});

// ----------------------------------------------------------
// makeNonce static
// ----------------------------------------------------------

describe('NonceSet - makeNonce', () => {
  it('generates unique nonces', () => {
    const n1 = NonceSet.makeNonce();
    const n2 = NonceSet.makeNonce();
    expect(n1).not.toBe(n2);
    expect(typeof n1).toBe('string');
    expect(n1.length).toBe(36); // UUID v4 length
  });
});
