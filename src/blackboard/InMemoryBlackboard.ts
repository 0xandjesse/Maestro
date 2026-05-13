// ============================================================
// Maestro Protocol — In-Memory Blackboard
// ============================================================
//
// Default implementation for local mode and testing.
// Last-write-wins on concurrent writes (v3 spec).
// Pub/sub via EventEmitter.
// ============================================================

import { EventEmitter } from 'events';
import {
  BlackboardEntry,
  SharedBlackboard,
  Unsubscribe,
} from './types.js';

export class InMemoryBlackboard extends EventEmitter implements SharedBlackboard {
  private store = new Map<string, BlackboardEntry>();
  private versions = new Map<string, number>();

  // ----------------------------------------------------------
  // Read
  // ----------------------------------------------------------

  async get(key: string): Promise<unknown> {
    return this.store.get(key)?.value ?? undefined;
  }

  async getEntry(key: string): Promise<BlackboardEntry | undefined> {
    return this.store.get(key);
  }

  async list(prefix?: string): Promise<string[]> {
    const keys = [...this.store.keys()];
    if (!prefix) return keys;
    return keys.filter(k => k.startsWith(prefix));
  }

  // ----------------------------------------------------------
  // Write
  // ----------------------------------------------------------

  async set(key: string, value: unknown, writtenBy: string): Promise<void> {
    const version = (this.versions.get(key) ?? 0) + 1;
    this.versions.set(key, version);

    const entry: BlackboardEntry = {
      key,
      value,
      writtenBy,
      writtenAt: Date.now(),
      version,
    };

    this.store.set(key, entry);
    this.emit(`key:${key}`, entry);
    this.emit('*', entry);
  }

  async delete(key: string, writtenBy: string): Promise<void> {
    if (!this.store.has(key)) return;

    const version = (this.versions.get(key) ?? 0) + 1;
    this.versions.set(key, version);

    // Emit a tombstone entry before deleting
    const tombstone: BlackboardEntry = {
      key,
      value: undefined,
      writtenBy,
      writtenAt: Date.now(),
      version,
    };

    this.store.delete(key);
    this.emit(`key:${key}`, tombstone);
    this.emit('*', tombstone);
  }

  // ----------------------------------------------------------
  // Subscribe
  // ----------------------------------------------------------

  subscribe(key: string, handler: (entry: BlackboardEntry) => void): Unsubscribe {
    const event = `key:${key}`;
    this.on(event, handler);
    return () => this.off(event, handler);
  }

  subscribeAll(handler: (entry: BlackboardEntry) => void): Unsubscribe {
    this.on('*', handler);
    return () => this.off('*', handler);
  }

  // ----------------------------------------------------------
  // Lifecycle
  // ----------------------------------------------------------

  async clear(): Promise<void> {
    this.store.clear();
    this.versions.clear();
  }

  async snapshot(): Promise<Record<string, BlackboardEntry>> {
    const result: Record<string, BlackboardEntry> = {};
    for (const [key, entry] of this.store) {
      result[key] = { ...entry };
    }
    return result;
  }

  // ----------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------

  size(): number {
    return this.store.size;
  }
}
