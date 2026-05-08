// ============================================================
// Maestro Protocol — Stage Provenance Enforcer
// ============================================================
//
// Enforces a Stage's ProvenancePolicy against an incoming
// MaestroMessage. This sits at L1 (Stage rules), not L0.
// ============================================================

import { MaestroMessage, ProvenanceMode } from '../types/index.js';
import { ProvenancePolicy } from '../types/index.js';

const MODE_RANK: Record<ProvenanceMode, number> = {
  'full': 4,
  'origin-neighborhood': 3,
  'bookends': 2,
  'tail-only': 1,
};

export interface EnforcementResult {
  accepted: boolean;
  reason?: string;
}

/**
 * Check whether a message satisfies a Stage's provenance policy.
 *
 * @param message  The incoming MaestroMessage
 * @param policy   The Stage's ProvenancePolicy
 */
export function enforceProvenancePolicy(
  message: MaestroMessage,
  policy: ProvenancePolicy,
): EnforcementResult {
  const requiresProvenance = policy.requiredFor?.includes(message.type);

  if (requiresProvenance && !message.provenance) {
    return {
      accepted: false,
      reason: `provenance_required_for_${message.type}`,
    };
  }

  if (!message.provenance) {
    return { accepted: true };
  }

  const provenance = message.provenance;

  if (policy.requireFullChainFor?.includes(message.type) && provenance.mode !== 'full') {
    return {
      accepted: false,
      reason: `full_chain_required_for_${message.type}`,
    };
  }

  const isTruncated = provenance.mode !== 'full';
  if (isTruncated && policy.allowTruncated === false) {
    return {
      accepted: false,
      reason: 'truncated_provenance_not_allowed',
    };
  }

  if (policy.minimumTruncationMode) {
    const minRank = MODE_RANK[policy.minimumTruncationMode];
    const actualRank = MODE_RANK[provenance.mode];
    if (actualRank < minRank) {
      return {
        accepted: false,
        reason: `provenance_mode_${provenance.mode}_below_minimum_${policy.minimumTruncationMode}`,
      };
    }
  }

  if (provenance.mode === 'full' && provenance.chain) {
    const chainLen = provenance.chain.length;

    if (policy.minChainLength !== undefined && chainLen < policy.minChainLength) {
      return {
        accepted: false,
        reason: `chain_too_short: ${chainLen} < ${policy.minChainLength}`,
      };
    }

    if (policy.maxChainLength !== undefined && chainLen > policy.maxChainLength) {
      return {
        accepted: false,
        reason: `chain_too_long: ${chainLen} > ${policy.maxChainLength}`,
      };
    }
  }

  return { accepted: true };
}
