// ============================================================
// Maestro Protocol — Agent TrustPolicy Engine
// ============================================================
// The protocol pipe is neutral. Agents are sovereign firewalls.
// TrustPolicy evaluates messages *before* they hit the cognitive loop.
// ============================================================

import { MaestroMessage, Provenance, VerificationResult } from '../types/index.js';
import { getProvenanceExtension } from '../extensions/index.js';
import { verifyProvenance } from '../provenance/verifier.js';
import { PublicKeyResolver } from '../types/index.js';

export type TrustLevel = 'permissive' | 'selective' | 'strict';

export interface TrustPolicyConfig {
  /** Trust level for this agent */
  level: TrustLevel;
  /** Whitelist of agentIds (wallet or agentId) whose signed messages are accepted in 'selective' or 'strict' modes */
  whitelist?: string[];
  /** PublicKeyResolver used to verify provenance in 'strict' mode */
  resolver?: PublicKeyResolver;
  /** Optional custom filter — runs after level-based checks */
  customFilter?: (msg: MaestroMessage) => { accept: boolean; reason?: string };
}

/**
 * Agent-local trust policy engine.
 *
 * Levels:
 *   permissive — Accept all messages. Mark unsigned with `[unverified]` note.
 *   selective  — Accept signed messages from whitelisted senders only.
 *                Sandbox/drop unsigned messages from non-whitelisted senders.
 *   strict     — Drop all messages lacking a valid provenance chain to a trusted root.
 */
export class TrustPolicy {
  readonly level: TrustLevel;
  private whitelist: Set<string>;
  private resolver?: PublicKeyResolver;
  private customFilter?: TrustPolicyConfig['customFilter'];

  constructor(config: TrustPolicyConfig) {
    this.level = config.level;
    this.whitelist = new Set(config.whitelist ?? []);
    this.resolver = config.resolver;
    this.customFilter = config.customFilter;
  }

  /**
   * Evaluate an incoming message against this agent's trust policy.
   * Returns an object indicating whether the message should be accepted,
   * and an optional reason / label for the cognitive loop.
   */
  async evaluate(message: MaestroMessage): Promise<{
    accept: boolean;
    label?: string;
    reason?: string;
  }> {
    // Permissive: accept everything, tag unverified
    if (this.level === 'permissive') {
      const prov = getProvenanceExtension(message);
      return { accept: true, label: prov ? 'verified' : '[unverified]' };
    }

    // Selective: require sender to be in whitelist; provenance is nice-to-have
    if (this.level === 'selective') {
      const senderKey = message.sender.wallet ?? message.sender.agentId;
      if (!this.whitelist.has(senderKey)) {
        return {
          accept: false,
          reason: `sender_not_whitelisted: ${senderKey}`,
        };
      }
      const prov = getProvenanceExtension(message);
      return { accept: true, label: prov ? 'verified' : '[unverified]' };
    }

    // Strict: drop unless provenance verifies cryptographically
    if (this.level === 'strict') {
      const prov = getProvenanceExtension(message);
      if (!prov) {
        return { accept: false, reason: 'missing_provenance' };
      }
      if (!this.resolver) {
        return { accept: false, reason: 'strict_mode_requires_resolver' };
      }
      const result = await verifyProvenance(message, this.resolver);
      if (!result.valid) {
        return { accept: false, reason: `invalid_provenance: ${result.status}` };
      }
      return { accept: true, label: 'verified' };
    }

    // Should not reach here, but default to deny
    return { accept: false, reason: 'unknown_trust_level' };
  }

  /**
   * Run custom filter if configured. Called after level-based evaluation.
   */
  runCustomFilter(message: MaestroMessage): { accept: boolean; reason?: string } | null {
    if (!this.customFilter) return null;
    return this.customFilter(message);
  }
}

/**
 * Convenience hook: wraps a MessageHandler with a TrustPolicy filter.
 * If the policy rejects the message, the handler is not invoked.
 */
export function withTrustPolicy(
  policy: TrustPolicy,
  handler: (msg: MaestroMessage) => Promise<void> | void,
): (msg: MaestroMessage) => Promise<void> {
  return async (msg: MaestroMessage) => {
    const result = await policy.evaluate(msg);
    if (!result.accept) {
      console.warn(`[TrustPolicy] Dropped message from ${msg.sender.agentId}: ${result.reason}`);
      return;
    }
    // Custom filter overlay
    const custom = policy.runCustomFilter(msg);
    if (custom && !custom.accept) {
      console.warn(`[TrustPolicy] Custom filter dropped message from ${msg.sender.agentId}: ${custom.reason}`);
      return;
    }
    await handler(msg);
  };
}
