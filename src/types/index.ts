// ============================================================
// Maestro Protocol — Core Types
// ============================================================

// ----------------------------------------------------------
// Agent Identity
// ----------------------------------------------------------

export interface AgentIdentity {
  agentId: string;
  wallet?: string;
  /** Optional LOCR credential binding */
  identityProof?: LocRCredential;
}

export interface LocRCredential {
  uid: string;
  issuer: string;
  /** Verification endpoint: issuer/verify?wallet=<wallet>&uid=<uid> */
  verificationUrl?: string;
}

// ----------------------------------------------------------
// Attestation Links
// ----------------------------------------------------------

export interface AttestationLink {
  /** agentId of the sender */
  from: string;
  /** agentId of the receiver — this agent signs the link */
  to: string;
  /** Unix epoch ms */
  timestamp: number;
  /**
   * Recipient signs: sha256(previousSignature + contentHash + timestamp)
   * For first hop: previousSignature = originalSignature
   */
  signature: string;
  /** Optional LOCR credential for identity binding */
  identityProof?: LocRCredential;
}

// ----------------------------------------------------------
// Truncation
// ----------------------------------------------------------

export type TruncationMode = 'tail-only' | 'bookends' | 'origin-neighborhood';
export type ProvenanceMode = 'full' | TruncationMode;

export interface TruncatedChain {
  mode: TruncationMode;

  /**
   * Origin neighborhood hops:
   * - 'origin-neighborhood': first N hops from originator
   * - 'bookends': first hop only (origin → first recipient)
   * - 'tail-only': empty / omitted
   */
  originNeighborhood?: AttestationLink[];

  /**
   * Recent custody — last M hops. Always present in truncated modes.
   */
  recentHops: AttestationLink[];

  /**
   * How many hops are hidden in the middle.
   * Required when truncating. Useful as a signal:
   * small = normal, large (>20) = warrants scrutiny.
   */
  hiddenMiddleCount: number;

  /**
   * SHA-256 of the complete chain before truncation.
   * Proves the full chain existed.
   */
  fullChainHash: string;

  /** Unix epoch ms when truncation occurred */
  truncatedAt: number;
}

// ----------------------------------------------------------
// Provenance
// ----------------------------------------------------------

export interface Provenance {
  /**
   * 'full'               — complete chain, chain field used
   * 'tail-only'          — privacy mode, truncatedChain field used
   * 'bookends'           — default, truncatedChain field used
   * 'origin-neighborhood'— forensics mode, truncatedChain field used
   */
  mode: ProvenanceMode;

  /** Present when mode === 'full' */
  chain?: AttestationLink[];

  /** Present when mode !== 'full' */
  truncatedChain?: TruncatedChain;

  /**
   * Original sender signs: sha256(content + timestamp + senderAgentId)
   * Present in ALL modes.
   */
  originalSignature: string;

  /** SHA-256 of message.content. Present in ALL modes. */
  contentHash: string;
}

// ----------------------------------------------------------
// Message Types
// ----------------------------------------------------------

export type MessageType =
  | 'chat'
  | 'blackboard-read'
  | 'blackboard-write'
  | 'capability'
  | 'software'
  | 'credential'
  | 'financial'
  | 'presence'
  | 'custom';

// ----------------------------------------------------------
// Maestro Message
// ----------------------------------------------------------

export interface MaestroMessage {
  /** Unique message ID (UUID v4 recommended) */
  id: string;

  /** Message type — informs provenance policy */
  type: MessageType;

  /** Message payload */
  content: string;

  /** Original sender */
  sender: AgentIdentity;

  /** Intended recipient agentId, or '*' for broadcast */
  recipient: string;

  /** Unix epoch ms — set by original sender, immutable */
  timestamp: number;

  /**
   * Optional provenance chain.
   * Agents and Venues determine when required based on risk profile.
   * See ProvenancePolicy for Venue-level enforcement.
   */
  provenance?: Provenance;

  /** Optional Venue context */
  venueId?: string;

  /** replyTo message ID for threading / backwards provenance */
  replyTo?: string;

  /** Protocol version */
  version?: string;
}

// ----------------------------------------------------------
// Venue Provenance Policy
// ----------------------------------------------------------

export interface ProvenancePolicy {
  /** Message types that require provenance */
  requiredFor?: MessageType[];

  /** Minimum number of visible attestation links */
  minChainLength?: number;

  /** Maximum number of attestation links to accept */
  maxChainLength?: number;

  /** Whether truncated chains are acceptable */
  allowTruncated?: boolean;

  /** Message types that require full (non-truncated) chains */
  requireFullChainFor?: MessageType[];

  /** Minimum required truncation mode (tail-only < bookends < origin-neighborhood < full) */
  minimumTruncationMode?: ProvenanceMode;
}

export interface VenueRules {
  venueId: string;
  name?: string;
  provenancePolicy?: ProvenancePolicy;
  [key: string]: unknown;
}

// ----------------------------------------------------------
// Key Resolver
// ----------------------------------------------------------

/**
 * Pluggable public key resolver.
 * Implementations: LOCR registry, DID document, local cache, on-chain registry.
 */
export interface PublicKeyResolver {
  /**
   * Resolve an agentId to its Ed25519 public key bytes.
   * Returns null if the agent is unknown.
   */
  resolve(agentId: string): Promise<Uint8Array | null>;
}

// ----------------------------------------------------------
// Verification Results
// ----------------------------------------------------------

export type VerificationStatus =
  | 'valid'
  | 'invalid-content-hash'
  | 'invalid-original-signature'
  | 'invalid-chain-link'
  | 'resolver-error'
  | 'missing-provenance';

export interface VerificationResult {
  valid: boolean;
  status: VerificationStatus;
  /** Which link index failed (0-based), if applicable */
  failedLinkIndex?: number;
  message?: string;
}
