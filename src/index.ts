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

// Blackboard
export type { BlackboardEntry, BlackboardBackend, SharedBlackboard, Unsubscribe } from './blackboard/index.js';
export { InMemoryBlackboard } from './blackboard/index.js';

// Transport
export type { MaestroConfig, MessageHandler, EventHandler, SendOptions, Artifact, WebhookEvent, DiscoveryConfig, DiscoveryMethod, AgentRegistration } from './transport/types.js';
export { MessageRouter } from './transport/MessageRouter.js';
export { LocalRegistry } from './transport/LocalRegistry.js';

// SDK
export { Maestro, VenueHandle } from './sdk/index.js';

// Venue
export type {
  Venue,
  VenueMember,
  VenueHierarchy,
  VenueStatus,
  VenueEvent,
  VenueEventType,
  EntryMode,
  MemberVisibility,
  Permission,
  JoinRequest,
  JoinResponse,
  JoinStatus,
  CreateVenueRequest,
  CreateVenueResponse,
  RoleTransferRequest,
  PermissionCheckResult,
} from './venue/index.js';
export { VenueManager, DEFAULT_PERMISSIONS, enforceProvenancePolicy } from './venue/index.js';
export type { EnforcementResult } from './venue/index.js';
