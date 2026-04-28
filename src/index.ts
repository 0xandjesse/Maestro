// ============================================================
// Maestro Protocol - Public API
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
  ConnectionRules,
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
export { InMemoryBlackboard, SQLiteBlackboard, BlackboardBridge } from './blackboard/index.js';

// Transport
export type { MaestroConfig, MessageHandler, EventHandler, SendOptions, Artifact, WebhookEvent, DiscoveryConfig, DiscoveryMethod, AgentRegistration } from './transport/types.js';
export { MessageRouter } from './transport/MessageRouter.js';
export { LocalRegistry } from './transport/LocalRegistry.js';
export { HttpTransport } from './transport/HttpTransport.js';
export type { HttpTransportConfig } from './transport/HttpTransport.js';
export { NetworkDelivery, deliverMessage } from './transport/NetworkDelivery.js';
export { MdnsDiscovery } from './transport/MdnsDiscovery.js';
export type { MdnsDiscoveryConfig } from './transport/MdnsDiscovery.js';
export type { DeliveryResult } from './transport/NetworkDelivery.js';
export { OpenClawAdapter } from './plugin/OpenClawAdapter.js';
export type { OpenClawAdapterConfig } from './plugin/OpenClawAdapter.js';
export { ConnectionBroker } from './transport/ConnectionBroker.js';
export type { ConnectionBrokerConfig, ConnectionInvitation, CreateConnectionResult } from './transport/ConnectionBroker.js';
export { ConnectionStore } from './transport/ConnectionStore.js';
export type { StoredConnection } from './transport/ConnectionStore.js';

// SDK
export { Maestro, ConnectionHandle } from './sdk/index.js';

// Connection
export type {
  Connection,
  ConnectionMember,
  ConnectionHierarchy,
  ConnectionStatus,
  ConnectionEvent,
  ConnectionEventType,
  EntryMode,
  MemberVisibility,
  Permission,
  JoinRequest,
  JoinResponse,
  JoinStatus,
  CreateConnectionRequest,
  CreateConnectionResponse,
  RoleTransferRequest,
  PermissionCheckResult,
} from './connection/index.js';
export { ConnectionManager, DEFAULT_PERMISSIONS, enforceProvenancePolicy } from './connection/index.js';
export type { EnforcementResult } from './connection/index.js';
