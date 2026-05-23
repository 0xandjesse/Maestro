// ============================================================
// Maestro Protocol — Extension Helpers
// ============================================================
// Central place to read/write extensions with known keys so the rest
// of the codebase doesn't hardcode string paths.
// ============================================================

import { MaestroMessage, Provenance } from '../types/index.js';

const PROVENANCE_KEY = 'provenance';

/**
 * Get the provenance object from a message's extensions, if present.
 * Returns undefined if the message has no extensions or no provenance extension.
 */
export function getProvenanceExtension(message: MaestroMessage): Provenance | undefined {
  const ext = message.extensions?.[PROVENANCE_KEY];
  if (!ext) return undefined;
  // Safety: ensure it at least looks like a Provenance object
  if (typeof ext === 'object' && ext !== null && 'originalSignature' in ext && 'contentHash' in ext) {
    return ext as Provenance;
  }
  return undefined;
}

/**
 * Set the provenance object into a message's extensions (mutates the message).
 */
export function setProvenanceExtension(message: MaestroMessage, provenance: Provenance): void {
  message.extensions = { ...(message.extensions ?? {}), [PROVENANCE_KEY]: provenance };
}
