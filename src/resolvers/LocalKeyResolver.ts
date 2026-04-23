// ============================================================
// Maestro Protocol — Local Key Resolver
// ============================================================
//
// In-memory key resolver for development, testing, and
// single-node deployments. Register agentId → publicKeyHex
// mappings at startup.
//
// Production deployments should implement PublicKeyResolver
// against LOCR, a DID registry, or an on-chain contract.
// ============================================================

import { PublicKeyResolver } from '../types/index.js';
import { hexToBytes } from '../crypto/index.js';

export class LocalKeyResolver implements PublicKeyResolver {
  private readonly keys = new Map<string, Uint8Array>();

  /**
   * Register an agent's public key.
   * @param agentId      The agent identifier
   * @param publicKeyHex Ed25519 public key as hex string
   */
  register(agentId: string, publicKeyHex: string): void {
    this.keys.set(agentId, hexToBytes(publicKeyHex));
  }

  /**
   * Bulk register from a map.
   */
  registerAll(entries: Record<string, string>): void {
    for (const [agentId, publicKeyHex] of Object.entries(entries)) {
      this.register(agentId, publicKeyHex);
    }
  }

  async resolve(agentId: string): Promise<Uint8Array | null> {
    return this.keys.get(agentId) ?? null;
  }

  /**
   * Remove an agent (e.g. to simulate key rotation / revocation).
   */
  revoke(agentId: string): void {
    this.keys.delete(agentId);
  }

  has(agentId: string): boolean {
    return this.keys.has(agentId);
  }
}
