// ============================================================
// Maestro Protocol — Provenance Chain Builder
// ============================================================
//
// Helpers for constructing and extending attestation chains.
// Each agent uses these when forwarding a message to add
// their recipient-signed attestation link.
// ============================================================

import {
  AttestationLink,
  MaestroMessage,
  Provenance,
  ProvenanceMode,
  TruncatedChain,
  TruncationMode,
} from '../types/index.js';

import {
  attestationPayload,
  hashConcat,
  hashString,
  originalSignaturePayload,
  sign,
} from '../crypto/index.js';

// ----------------------------------------------------------
// Create Original Provenance (Sender)
// ----------------------------------------------------------

/**
 * Called by the original message sender to initialise provenance.
 * Signs content + timestamp + senderAgentId.
 *
 * @param message       The MaestroMessage being sent (must have content, timestamp, sender)
 * @param privateKeyHex Sender's Ed25519 private key
 * @param mode          Provenance mode to initialise ('full' by default)
 * @returns A Provenance object to attach to the message
 */
export async function createProvenance(
  message: Pick<MaestroMessage, 'content' | 'timestamp' | 'sender'>,
  privateKeyHex: string,
  mode: ProvenanceMode = 'full',
): Promise<Provenance> {
  const payload = originalSignaturePayload(
    message.content,
    message.timestamp,
    message.sender.agentId,
  );

  const originalSignature = await sign(payload, privateKeyHex);
  const contentHash = hashString(message.content);

  if (mode === 'full') {
    return {
      mode: 'full',
      chain: [],
      originalSignature,
      contentHash,
    };
  }

  // Truncated modes start with an empty truncatedChain —
  // the first recipient will populate originNeighborhood / recentHops
  return {
    mode,
    truncatedChain: {
      mode: mode as TruncationMode,
      originNeighborhood: [],
      recentHops: [],
      hiddenMiddleCount: 0,
      fullChainHash: '',   // populated once the chain has hops
      truncatedAt: Date.now(),
    },
    originalSignature,
    contentHash,
  };
}

// ----------------------------------------------------------
// Add Attestation Link (Recipient / Forwarder)
// ----------------------------------------------------------

/**
 * Called by a recipient agent when they want to attest receipt and
 * optionally forward the message with provenance.
 *
 * Adds a recipient-signed attestation link to a full chain.
 * For truncated chains, use addAttestationTruncated().
 *
 * @param provenance    The existing Provenance from the received message
 * @param from          agentId of the agent who sent it to us
 * @param recipientId   Our own agentId
 * @param privateKeyHex Our Ed25519 private key
 * @returns Updated Provenance with our attestation appended
 */
export async function addAttestation(
  provenance: Provenance,
  from: string,
  recipientId: string,
  privateKeyHex: string,
): Promise<Provenance> {
  if (provenance.mode !== 'full') {
    throw new Error(
      'addAttestation() is for full chains. Use addAttestationTruncated() for truncated chains.',
    );
  }

  const chain = provenance.chain ?? [];
  const previousSignature =
    chain.length === 0
      ? provenance.originalSignature
      : chain[chain.length - 1].signature;

  const payload = attestationPayload(
    previousSignature,
    provenance.contentHash,
    Date.now(),
  );

  const timestamp = Date.now();
  const signature = await sign(
    attestationPayload(previousSignature, provenance.contentHash, timestamp),
    privateKeyHex,
  );

  const link: AttestationLink = { from, to: recipientId, timestamp, signature };

  return {
    ...provenance,
    chain: [...chain, link],
  };
}

// ----------------------------------------------------------
// Truncation
// ----------------------------------------------------------

/**
 * Truncate a full provenance chain according to the desired mode.
 *
 * - 'tail-only':           Privacy mode — hide origin, keep only recentHops
 * - 'bookends':            Default — keep first hop + recentHops
 * - 'origin-neighborhood': Forensics — keep first N hops + recentHops
 *
 * @param provenance      Full provenance to truncate
 * @param mode            Target truncation mode
 * @param recentHopCount  How many recent hops to keep (default: 2)
 * @param originHopCount  How many origin hops to keep for origin-neighborhood (default: 3)
 * @returns New Provenance in the specified truncated mode
 */
export function truncateProvenance(
  provenance: Provenance,
  mode: TruncationMode,
  recentHopCount = 2,
  originHopCount = 3,
): Provenance {
  if (provenance.mode !== 'full' || !provenance.chain) {
    throw new Error('truncateProvenance() requires a full provenance chain.');
  }

  const chain = provenance.chain;
  const fullChainHash = hashString(JSON.stringify(chain));

  let originNeighborhood: AttestationLink[] = [];
  let recentHops: AttestationLink[];
  let hiddenMiddleCount: number;

  if (mode === 'tail-only') {
    // Hide everything before recentHops
    recentHops = chain.slice(-recentHopCount);
    hiddenMiddleCount = Math.max(0, chain.length - recentHopCount);
    originNeighborhood = [];
  } else if (mode === 'bookends') {
    // Keep first hop + last recentHopCount hops
    const origin = chain.slice(0, 1);
    const recent = chain.slice(-recentHopCount);
    // Avoid duplication when chain is very short
    const overlapStart = Math.max(1, chain.length - recentHopCount);
    originNeighborhood = origin;
    recentHops = chain.slice(overlapStart);
    hiddenMiddleCount = Math.max(0, overlapStart - 1);
  } else {
    // origin-neighborhood: first N + last recentHopCount
    const origin = chain.slice(0, originHopCount);
    const recentStart = Math.max(originHopCount, chain.length - recentHopCount);
    recentHops = chain.slice(recentStart);
    hiddenMiddleCount = Math.max(0, recentStart - originHopCount);
    originNeighborhood = origin;
  }

  const truncatedChain: TruncatedChain = {
    mode,
    originNeighborhood,
    recentHops,
    hiddenMiddleCount,
    fullChainHash,
    truncatedAt: Date.now(),
  };

  return {
    mode,
    truncatedChain,
    originalSignature: provenance.originalSignature,
    contentHash: provenance.contentHash,
  };
}

/**
 * Add an attestation link to a truncated chain (updates recentHops).
 * The new link is appended to recentHops; fullChainHash is updated to reflect
 * the new complete logical chain.
 */
export async function addAttestationTruncated(
  provenance: Provenance,
  from: string,
  recipientId: string,
  privateKeyHex: string,
): Promise<Provenance> {
  if (!provenance.truncatedChain) {
    throw new Error('addAttestationTruncated() requires a truncated provenance chain.');
  }

  const tc = provenance.truncatedChain;
  const recentHops = tc.recentHops;

  const previousSignature =
    recentHops.length === 0
      ? provenance.originalSignature
      : recentHops[recentHops.length - 1].signature;

  const timestamp = Date.now();
  const signature = await sign(
    attestationPayload(previousSignature, provenance.contentHash, timestamp),
    privateKeyHex,
  );

  const newLink: AttestationLink = { from, to: recipientId, timestamp, signature };

  // Rebuild fullChainHash to include the new hop
  const newFullChainHash = hashConcat(tc.fullChainHash, JSON.stringify(newLink));

  return {
    ...provenance,
    truncatedChain: {
      ...tc,
      recentHops: [...recentHops, newLink],
      fullChainHash: newFullChainHash,
      truncatedAt: Date.now(),
    },
  };
}
