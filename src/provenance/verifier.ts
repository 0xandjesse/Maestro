// ============================================================
// Maestro Protocol — Provenance Verifier
// ============================================================
//
// Verifies attestation chains against the spec's signature format.
// Uses a pluggable PublicKeyResolver — the protocol does not mandate
// a specific key registry. See types/index.ts for the resolver interface.
// ============================================================

import { AttestationLink, MaestroMessage, Provenance, PublicKeyResolver, VerificationResult } from '../types/index.js';
import { attestationPayload, bytesToHex, hashString, originalSignaturePayload, verify } from '../crypto/index.js';

// ----------------------------------------------------------
// Primary Verification Entry Point
// ----------------------------------------------------------

/**
 * Verify a message's provenance chain.
 *
 * Checks:
 *  1. contentHash matches message.content
 *  2. originalSignature is valid (signed by message.sender)
 *  3. Each attestation link signature is valid (signed by link.to)
 *
 * For truncated chains, verifies the visible portion only.
 * fullChainHash is not re-verified here (it's a commitment, not a proof).
 *
 * @param message   The MaestroMessage containing provenance
 * @param resolver  Public key resolver implementation
 * @returns VerificationResult
 */
export async function verifyProvenance(
  message: MaestroMessage,
  resolver: PublicKeyResolver,
): Promise<VerificationResult> {
  if (!message.provenance) {
    return {
      valid: false,
      status: 'missing-provenance',
      message: 'Message has no provenance field.',
    };
  }

  const provenance = message.provenance;

  // Step 1: Verify content hash
  const expectedContentHash = hashString(message.content);
  if (expectedContentHash !== provenance.contentHash) {
    return {
      valid: false,
      status: 'invalid-content-hash',
      message: `Content hash mismatch. Expected ${expectedContentHash}, got ${provenance.contentHash}`,
    };
  }

  // Step 2: Verify original signature (sender signed the content)
  const originalPayload = originalSignaturePayload(
    message.content,
    message.timestamp,
    message.sender.agentId,
  );

  try {
    const senderPublicKey = await resolver.resolve(message.sender.agentId);
    if (!senderPublicKey) {
      return {
        valid: false,
        status: 'resolver-error',
        message: `Could not resolve public key for sender: ${message.sender.agentId}`,
      };
    }

    const originalValid = await verify(
      originalPayload,
      provenance.originalSignature,
      bytesToHex(senderPublicKey),
    );

    if (!originalValid) {
      return {
        valid: false,
        status: 'invalid-original-signature',
        message: `Original signature invalid for sender: ${message.sender.agentId}`,
      };
    }
  } catch (err) {
    return {
      valid: false,
      status: 'resolver-error',
      message: `Resolver threw for sender ${message.sender.agentId}: ${String(err)}`,
    };
  }

  // Step 3: Verify attestation links (visible portion)
  const links = getVisibleLinks(provenance);

  if (links.length > 0) {
    const result = await verifyLinks(links, provenance.originalSignature, provenance.contentHash, resolver);
    if (!result.valid) return result;
  }

  return { valid: true, status: 'valid' };
}

// ----------------------------------------------------------
// Link Verification
// ----------------------------------------------------------

/**
 * Verify a sequence of attestation links.
 * Each link's signature must be valid: recipient (link.to) signs
 * hash(previousSignature + contentHash + timestamp).
 */
async function verifyLinks(
  links: AttestationLink[],
  originalSignature: string,
  contentHash: string,
  resolver: PublicKeyResolver,
): Promise<VerificationResult> {
  let previousSignature = originalSignature;

  for (let i = 0; i < links.length; i++) {
    const link = links[i];
    const payload = attestationPayload(previousSignature, contentHash, link.timestamp);

    try {
      const recipientPublicKey = await resolver.resolve(link.to);
      if (!recipientPublicKey) {
        return {
          valid: false,
          status: 'resolver-error',
          failedLinkIndex: i,
          message: `Could not resolve public key for agent: ${link.to}`,
        };
      }

      const linkValid = await verify(payload, link.signature, bytesToHex(recipientPublicKey));
      if (!linkValid) {
        return {
          valid: false,
          status: 'invalid-chain-link',
          failedLinkIndex: i,
          message: `Attestation link ${i} invalid. Agent ${link.to} signature did not verify.`,
        };
      }
    } catch (err) {
      return {
        valid: false,
        status: 'resolver-error',
        failedLinkIndex: i,
        message: `Resolver threw for agent ${link.to}: ${String(err)}`,
      };
    }

    previousSignature = link.signature;
  }

  return { valid: true, status: 'valid' };
}

// ----------------------------------------------------------
// Helpers
// ----------------------------------------------------------

/**
 * Extract the visible attestation links from a Provenance,
 * regardless of mode. For truncated chains, concatenates
 * originNeighborhood + recentHops (in that order).
 *
 * Note: there may be a gap (hiddenMiddleCount) between the two
 * segments. Verification of the recentHops segment cannot chain
 * from originNeighborhood — each segment is verified independently
 * from the last known signature of the previous visible segment.
 */
function getVisibleLinks(provenance: Provenance): AttestationLink[] {
  if (provenance.mode === 'full') {
    return provenance.chain ?? [];
  }

  const tc = provenance.truncatedChain;
  if (!tc) return [];

  const origin = tc.originNeighborhood ?? [];
  const recent = tc.recentHops ?? [];

  return [...origin, ...recent];
}

/**
 * Verify a truncated chain's visible portions independently.
 *
 * For truncated chains with a hidden middle:
 * - originNeighborhood verifies from originalSignature
 * - recentHops cannot be verified to chain from originNeighborhood
 *   (the linking signatures are hidden)
 * - recentHops CAN be verified internally (each hop chains to the next)
 *
 * This function returns a detailed breakdown of what was and wasn't verified.
 */
export async function verifyTruncatedChainSegments(
  provenance: Provenance,
  originalSignature: string,
  resolver: PublicKeyResolver,
): Promise<{
  originSegmentValid: boolean;
  recentSegmentInternallyValid: boolean;
  hiddenMiddleCount: number;
  note: string;
}> {
  if (provenance.mode === 'full') {
    throw new Error('verifyTruncatedChainSegments() is for truncated chains only.');
  }

  const tc = provenance.truncatedChain;
  if (!tc) {
    return {
      originSegmentValid: false,
      recentSegmentInternallyValid: false,
      hiddenMiddleCount: 0,
      note: 'No truncatedChain present.',
    };
  }

  const contentHash = provenance.contentHash;

  // Verify origin neighborhood (chains from originalSignature)
  let originSegmentValid = true;
  if (tc.originNeighborhood && tc.originNeighborhood.length > 0) {
    const result = await verifyLinks(
      tc.originNeighborhood,
      originalSignature,
      contentHash,
      resolver,
    );
    originSegmentValid = result.valid;
  }

  // Verify recent hops internally (each chains to the next within the segment)
  // We cannot verify the first recent hop's connection to the hidden middle.
  let recentSegmentInternallyValid = true;
  if (tc.recentHops.length > 1) {
    const internalLinks = tc.recentHops.slice(1); // skip first — no known previous sig
    const firstKnownSig = tc.recentHops[0].signature;
    const result = await verifyLinks(internalLinks, firstKnownSig, contentHash, resolver);
    recentSegmentInternallyValid = result.valid;
  }

  return {
    originSegmentValid,
    recentSegmentInternallyValid,
    hiddenMiddleCount: tc.hiddenMiddleCount,
    note:
      tc.hiddenMiddleCount > 0
        ? `${tc.hiddenMiddleCount} hops hidden. Recent segment verified internally only — cannot chain to origin segment across hidden middle.`
        : 'No hidden hops.',
  };
}
