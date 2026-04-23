// ============================================================
// Maestro Protocol — Public API
// ============================================================

// Types
export type {
  AgentIdentity,
  AttestationLink,
  LocRCredential,
  MaestroMessage,
  MessageType,
  Provenance,
  ProvenanceMode,
  ProvenancePolicy,
  PublicKeyResolver,
  TruncatedChain,
  TruncationMode,
  VerificationResult,
  VerificationStatus,
  VenueRules,
} from './types/index.js';

// Crypto primitives
export {
  generateKeyPair,
  getPublicKey,
  hashString,
  hashConcat,
  sign,
  verify,
  originalSignaturePayload,
  attestationPayload,
} from './crypto/index.js';

// Provenance builder
export {
  createProvenance,
  addAttestation,
  addAttestationTruncated,
  truncateProvenance,
} from './provenance/builder.js';

// Provenance verifier
export {
  verifyProvenance,
  verifyTruncatedChainSegments,
} from './provenance/verifier.js';

// Message factory
export { createMessage } from './message/index.js';
export type { CreateMessageOptions } from './message/index.js';

// Resolvers
export { LocalKeyResolver } from './resolvers/LocalKeyResolver.js';
