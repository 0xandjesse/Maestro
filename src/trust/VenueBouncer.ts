// ============================================================
// Maestro Protocol — Venue Bouncer
// ============================================================
// The Venue gate enforces Connection-level provenance policies.
// It sits at the Venue periphery, not the protocol core.
// If a message fails the Venue's check, it returns a
// ProvenanceRequired error. The message is dropped at the gate.
// ============================================================

import { MaestroMessage, ProvenancePolicy } from '../types/index.js';
import { getProvenanceExtension } from '../extensions/index.js';

export interface BouncerResult {
  allowed: boolean;
  /** Human-readable reason when blocked */
  reason?: string;
  /** Machine-readable error code */
  error?: 'ProvenanceRequired' | 'Forbidden';
}

/**
 * Venue Bouncer — enforces a Connection's provenance policy against
 * an incoming MaestroMessage. Operates on extensions.provenance.
 *
 * This is the "Venue gate" from the Sovereign Trust spec.
 * The protocol pipe is neutral; the Venue decides what it accepts.
 */
export function verificationGate(
  message: MaestroMessage,
  policy: ProvenancePolicy,
): BouncerResult {
  const provenance = getProvenanceExtension(message);

  // Is provenance required for this message type?
  const requiresProvenance = policy.requiredFor?.includes(message.type);

  if (requiresProvenance && !provenance) {
    return {
      allowed: false,
      error: 'ProvenanceRequired',
      reason: `provenance_required_for_${message.type}`,
    };
  }

  if (!provenance) {
    return { allowed: true };
  }

  // Full chain required for certain types?
  if (policy.requireFullChainFor?.includes(message.type) && provenance.mode !== 'full') {
    return {
      allowed: false,
      error: 'ProvenanceRequired',
      reason: `full_chain_required_for_${message.type}`,
    };
  }

  // Truncated chains allowed?
  const isTruncated = provenance.mode !== 'full';
  if (isTruncated && policy.allowTruncated === false) {
    return {
      allowed: false,
      error: 'ProvenanceRequired',
      reason: 'truncated_provenance_not_allowed',
    };
  }

  // Minimum truncation mode check
  const MODE_RANK: Record<import('../types/index.js').ProvenanceMode, number> = {
    'full': 4,
    'origin-neighborhood': 3,
    'bookends': 2,
    'tail-only': 1,
  };

  if (policy.minimumTruncationMode) {
    const minRank = MODE_RANK[policy.minimumTruncationMode];
    const actualRank = MODE_RANK[provenance.mode];
    if (actualRank < minRank) {
      return {
        allowed: false,
        error: 'ProvenanceRequired',
        reason: `provenance_mode_${provenance.mode}_below_minimum_${policy.minimumTruncationMode}`,
      };
    }
  }

  // Chain length checks (for full chains)
  if (provenance.mode === 'full' && provenance.chain) {
    const chainLen = provenance.chain.length;

    if (policy.minChainLength !== undefined && chainLen < policy.minChainLength) {
      return {
        allowed: false,
        error: 'ProvenanceRequired',
        reason: `chain_too_short: ${chainLen} < ${policy.minChainLength}`,
      };
    }

    if (policy.maxChainLength !== undefined && chainLen > policy.maxChainLength) {
      return {
        allowed: false,
        error: 'ProvenanceRequired',
        reason: `chain_too_long: ${chainLen} > ${policy.maxChainLength}`,
      };
    }
  }

  return { allowed: true };
}
