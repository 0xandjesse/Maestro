// ============================================================
// Maestro Protocol — Local Agent Registry
// ============================================================
//
// File-based agent registry for local discovery mode.
// Agents register their agentId + webhookEndpoint here.
// Other agents read this to discover peers.
//
// For containers / multi-process setups on one machine.
// mDNS and Redis registries are future implementations.
// ============================================================

import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'fs';
import { dirname } from 'path';
import { AgentRegistration } from './types.js';

export class LocalRegistry {
  private filePath: string;
  private cache = new Map<string, AgentRegistration>();

  constructor(filePath: string) {
    this.filePath = filePath;
    this.load();
  }

  // ----------------------------------------------------------
  // Registration
  // ----------------------------------------------------------

  register(registration: Omit<AgentRegistration, 'registeredAt' | 'lastSeen'>): void {
    const entry: AgentRegistration = {
      ...registration,
      registeredAt: this.cache.get(registration.agentId)?.registeredAt ?? Date.now(),
      lastSeen: Date.now(),
    };
    this.cache.set(registration.agentId, entry);
    this.persist();
  }

  heartbeat(agentId: string): void {
    const entry = this.cache.get(agentId);
    if (entry) {
      entry.lastSeen = Date.now();
      this.persist();
    }
  }

  unregister(agentId: string): void {
    this.cache.delete(agentId);
    this.persist();
  }

  // ----------------------------------------------------------
  // Discovery
  // ----------------------------------------------------------

  lookup(agentId: string): AgentRegistration | undefined {
    this.load(); // Refresh from disk for cross-process visibility
    return this.cache.get(agentId);
  }

  listAll(): AgentRegistration[] {
    this.load();
    return [...this.cache.values()];
  }

  /**
   * Return agents seen within the last `maxAgeMs` milliseconds.
   */
  listActive(maxAgeMs = 60_000): AgentRegistration[] {
    const cutoff = Date.now() - maxAgeMs;
    return this.listAll().filter(a => a.lastSeen >= cutoff);
  }

  // ----------------------------------------------------------
  // Persistence
  // ----------------------------------------------------------

  private load(): void {
    if (!existsSync(this.filePath)) return;
    try {
      const raw = readFileSync(this.filePath, 'utf8');
      const data: AgentRegistration[] = JSON.parse(raw);
      this.cache.clear();
      for (const entry of data) {
        this.cache.set(entry.agentId, entry);
      }
    } catch {
      // File corrupt or missing — start fresh
    }
  }

  private persist(): void {
    const dir = dirname(this.filePath);
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
    const data = [...this.cache.values()];
    writeFileSync(this.filePath, JSON.stringify(data, null, 2), 'utf8');
  }
}
