// ============================================================
// Maestro Protocol — Blackboard Types
// ============================================================

export type Unsubscribe = () => void;

export interface BlackboardEntry {
  key: string;
  value: unknown;
  writtenBy: string;   // agentId
  writtenAt: number;   // Unix epoch ms
  version: number;     // Monotonically increasing per key
}

/**
 * The Shared Blackboard interface — as specified in v3.1.
 * Implementations: InMemoryBlackboard (local), platform adapters (network).
 */
export interface SharedBlackboard {
  // Read
  get(key: string): Promise<unknown>;
  list(prefix?: string): Promise<string[]>;
  getEntry(key: string): Promise<BlackboardEntry | undefined>;

  // Write
  set(key: string, value: unknown, writtenBy: string): Promise<void>;
  delete(key: string, writtenBy: string): Promise<void>;

  // Subscribe to a specific key
  subscribe(key: string, handler: (entry: BlackboardEntry) => void): Unsubscribe;

  // Subscribe to all changes
  subscribeAll(handler: (entry: BlackboardEntry) => void): Unsubscribe;

  // Lifecycle
  clear(): Promise<void>;
  snapshot(): Promise<Record<string, BlackboardEntry>>;
}

/**
 * Platform-provided adapter interface.
 * Platforms implement this; agents never call it directly.
 */
export interface BlackboardBackend {
  get(venueId: string, key: string): Promise<BlackboardEntry | undefined>;
  set(venueId: string, entry: BlackboardEntry): Promise<void>;
  delete(venueId: string, key: string): Promise<void>;
  list(venueId: string, prefix?: string): Promise<string[]>;
  snapshot(venueId: string): Promise<Record<string, BlackboardEntry>>;
}
