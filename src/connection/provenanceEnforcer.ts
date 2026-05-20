// ============================================================
// Maestro Protocol - Connection Provenance Enforcer
// ============================================================
//
// Enforces a Connection's ProvenancePolicy against an incoming
// MaestroMessage. This sits at L1 (Connection rules), not L0.
// ============================================================

import { MaestroMessage, ProvenanceMode, ProvenancePolicy } from '../types/index.js';
import { getProvenanceExtension } from '../extensions/index.js';

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
 * Check whether a message satisfies a Connection's provenance policy.
 *
 * @param message  The incoming MaestroMessage
 * @param policy   The Connection's ProvenancePolicy
 */
export function enforceProvenancePolicy(
  message: MaestroMessage,
  policy: ProvenancePolicy,
): EnforcementResult {
  const provenance = getProvenanceExtension(message);

  // Is provenance required for this message type?
  const requiresProvenance = policy.requiredFor?.includes(message.type);

  if (requiresProvenance && !provenance) {
    return {
      accepted: false,
      reason: `ProvenanceRequired: provenance_required_for_${message.type}`,
    };
  }

  if (!provenance) {
    // Provenance not required and not present - accepted
    return { accepted: true };
  }

  // Full chain required for certain types?
  if (policy.requireFullChainFor?.includes(message.type) && provenance.mode !== 'full') {
    return {
      accepted: false,
      reason: `full_chain_required_for_${message.type}`,
    };
  }

  // Truncated chains allowed?
  const isTruncated = provenance.mode !== 'full';
  if (isTruncated && policy.allowTruncated === false) {
    return {
      accepted: false,
      reason: 'truncated_provenance_not_allowed',
    };
  }

  // Minimum truncation mode check
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

  // Chain length checks (for full chains)
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
