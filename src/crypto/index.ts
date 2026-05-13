// ============================================================
// Maestro Protocol — Cryptographic Primitives
// ============================================================
//
// Ed25519 signatures via @noble/ed25519
// SHA-256 hashing via @noble/hashes
//
// All functions are async to support future HSM / remote signer
// integrations without API changes.
// ============================================================

import * as ed from '@noble/ed25519';
import { sha256 } from '@noble/hashes/sha256';
import { sha512 } from '@noble/hashes/sha512';
import { bytesToHex, hexToBytes, utf8ToBytes } from '@noble/hashes/utils';

// @noble/ed25519 v2 requires sha512 to be wired in for Node environments
ed.etc.sha512Sync = (...m) => sha512(ed.etc.concatBytes(...m));

export { bytesToHex, hexToBytes, utf8ToBytes };

// ----------------------------------------------------------
// Hashing
// ----------------------------------------------------------

/**
 * SHA-256 hash of a string. Returns lowercase hex string.
 */
export function hashString(input: string): string {
  return bytesToHex(sha256(utf8ToBytes(input)));
}

/**
 * SHA-256 hash of concatenated strings. Returns lowercase hex string.
 */
export function hashConcat(...parts: string[]): string {
  return hashString(parts.join(''));
}

/**
 * SHA-256 hash of raw bytes. Returns lowercase hex string.
 */
export function hashBytes(input: Uint8Array): string {
  return bytesToHex(sha256(input));
}

// ----------------------------------------------------------
// Key Generation
// ----------------------------------------------------------

/**
 * Generate a new Ed25519 key pair.
 * Returns private key (32 bytes) and public key (32 bytes) as hex strings.
 */
export function generateKeyPair(): { privateKey: string; publicKey: string } {
  const privateKey = ed.utils.randomPrivateKey();
  const publicKey = ed.getPublicKey(privateKey);
  return {
    privateKey: bytesToHex(privateKey),
    publicKey: bytesToHex(publicKey),
  };
}

/**
 * Derive public key from private key hex string.
 */
export function getPublicKey(privateKeyHex: string): string {
  return bytesToHex(ed.getPublicKey(hexToBytes(privateKeyHex)));
}

// ----------------------------------------------------------
// Signing
// ----------------------------------------------------------

/**
 * Sign a message string with an Ed25519 private key.
 *
 * @param message  The string to sign (will be UTF-8 encoded then SHA-256 hashed)
 * @param privateKeyHex  Ed25519 private key as hex string
 * @returns Signature as hex string
 */
export async function sign(message: string, privateKeyHex: string): Promise<string> {
  const msgBytes = utf8ToBytes(message);
  const msgHash = sha256(msgBytes);
  const sig = await ed.signAsync(msgHash, hexToBytes(privateKeyHex));
  return bytesToHex(sig);
}

/**
 * Verify an Ed25519 signature.
 *
 * @param message      The original string that was signed
 * @param signatureHex Signature as hex string
 * @param publicKeyHex Public key as hex string
 * @returns true if valid
 */
export async function verify(
  message: string,
  signatureHex: string,
  publicKeyHex: string,
): Promise<boolean> {
  try {
    const msgBytes = utf8ToBytes(message);
    const msgHash = sha256(msgBytes);
    return await ed.verifyAsync(
      hexToBytes(signatureHex),
      msgHash,
      hexToBytes(publicKeyHex),
    );
  } catch {
    return false;
  }
}

// ----------------------------------------------------------
// Payload Helpers (spec-defined canonical formats)
// ----------------------------------------------------------

/**
 * Canonical payload for the original sender's signature.
 * Spec: sha256(content + timestamp + senderAgentId)
 */
export function originalSignaturePayload(
  content: string,
  timestamp: number,
  senderAgentId: string,
): string {
  return hashConcat(content, String(timestamp), senderAgentId);
}

/**
 * Canonical payload for an attestation link signature.
 * Spec: sha256(previousSignature + contentHash + timestamp)
 */
export function attestationPayload(
  previousSignature: string,
  contentHash: string,
  timestamp: number,
): string {
  return hashConcat(previousSignature, contentHash, String(timestamp));
}
