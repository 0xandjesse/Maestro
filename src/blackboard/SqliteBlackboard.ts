// ============================================================
// Maestro Protocol — SQLite Blackboard
// ============================================================
//
// Persistent Blackboard backend using better-sqlite3.
// Drop-in replacement for InMemoryBlackboard.
//
// Each Blackboard instance gets its own DB file (or uses
// an in-memory DB if path is ':memory:').
//
// Pub/sub still uses EventEmitter — SQLite handles persistence,
// not cross-process events. For cross-process pub/sub, a
// platform adapter (e.g. Redis) is the right tool.
//
// Last-write-wins on concurrent writes (v3 spec).
// ============================================================

import Database, { Database as DB } from 'better-sqlite3';
import { EventEmitter } from 'events';
import {
  BlackboardEntry,
  SharedBlackboard,
  Unsubscribe,
} from './types.js';

export interface SqliteBlackboardOptions {
  /** Path to SQLite file, or ':memory:' for ephemeral. Default: ':memory:' */
  path?: string;
  /** Venue ID — used as a namespace prefix in multi-venue DBs */
  venueId?: string;
}

export class SqliteBlackboard extends EventEmitter implements SharedBlackboard {
  private db: DB;
  private venueId: string;

  constructor(options: SqliteBlackboardOptions = {}) {
    super();
    this.venueId = options.venueId ?? 'default';
    this.db = new Database(options.path ?? ':memory:');
    this.init();
  }

  // ----------------------------------------------------------
  // Schema
  // ----------------------------------------------------------

  private init(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS blackboard (
        venue_id   TEXT    NOT NULL,
        key        TEXT    NOT NULL,
        value      TEXT    NOT NULL,   -- JSON-serialised
        written_by TEXT    NOT NULL,
        written_at INTEGER NOT NULL,
        version    INTEGER NOT NULL,
        PRIMARY KEY (venue_id, key)
      );

      CREATE INDEX IF NOT EXISTS idx_bb_venue
        ON blackboard (venue_id);
    `);
  }

  // ----------------------------------------------------------
  // Read
  // ----------------------------------------------------------

  async get(key: string): Promise<unknown> {
    const entry = this.getRow(key);
    return entry ? JSON.parse(entry.value) : undefined;
  }

  async getEntry(key: string): Promise<BlackboardEntry | undefined> {
    const row = this.getRow(key);
    if (!row) return undefined;
    return this.rowToEntry(row);
  }

  async list(prefix?: string): Promise<string[]> {
    if (prefix) {
      const stmt = this.db.prepare(
        'SELECT key FROM blackboard WHERE venue_id = ? AND key LIKE ?'
      );
      const rows = stmt.all(this.venueId, `${prefix}%`) as { key: string }[];
      return rows.map(r => r.key);
    }
    const stmt = this.db.prepare(
      'SELECT key FROM blackboard WHERE venue_id = ?'
    );
    const rows = stmt.all(this.venueId) as { key: string }[];
    return rows.map(r => r.key);
  }

  // ----------------------------------------------------------
  // Write
  // ----------------------------------------------------------

  async set(key: string, value: unknown, writtenBy: string): Promise<void> {
    const existing = this.getRow(key);
    const version = (existing?.version ?? 0) + 1;

    const stmt = this.db.prepare(`
      INSERT INTO blackboard (venue_id, key, value, written_by, written_at, version)
      VALUES (?, ?, ?, ?, ?, ?)
      ON CONFLICT (venue_id, key) DO UPDATE SET
        value      = excluded.value,
        written_by = excluded.written_by,
        written_at = excluded.written_at,
        version    = excluded.version
    `);

    stmt.run(
      this.venueId,
      key,
      JSON.stringify(value),
      writtenBy,
      Date.now(),
      version,
    );

    const entry = await this.getEntry(key) as BlackboardEntry;
    this.emit(`key:${key}`, entry);
    this.emit('*', entry);
  }

  async delete(key: string, writtenBy: string): Promise<void> {
    const existing = this.getRow(key);
    if (!existing) return;

    const version = existing.version + 1;

    // Emit tombstone before deleting
    const tombstone: BlackboardEntry = {
      key,
      value: undefined,
      writtenBy,
      writtenAt: Date.now(),
      version,
    };

    const stmt = this.db.prepare(
      'DELETE FROM blackboard WHERE venue_id = ? AND key = ?'
    );
    stmt.run(this.venueId, key);

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
    this.db.prepare('DELETE FROM blackboard WHERE venue_id = ?').run(this.venueId);
  }

  async snapshot(): Promise<Record<string, BlackboardEntry>> {
    const stmt = this.db.prepare('SELECT * FROM blackboard WHERE venue_id = ?');
    const rows = stmt.all(this.venueId) as RawRow[];
    const result: Record<string, BlackboardEntry> = {};
    for (const row of rows) {
      result[row.key] = this.rowToEntry(row);
    }
    return result;
  }

  /** Close the underlying DB connection. Call when the Venue is closed. */
  close(): void {
    this.db.close();
  }

  // ----------------------------------------------------------
  // Internal
  // ----------------------------------------------------------

  private getRow(key: string): RawRow | undefined {
    const stmt = this.db.prepare(
      'SELECT * FROM blackboard WHERE venue_id = ? AND key = ?'
    );
    return stmt.get(this.venueId, key) as RawRow | undefined;
  }

  private rowToEntry(row: RawRow): BlackboardEntry {
    return {
      key: row.key,
      value: JSON.parse(row.value),
      writtenBy: row.written_by,
      writtenAt: row.written_at,
      version: row.version,
    };
  }
}

interface RawRow {
  venue_id: string;
  key: string;
  value: string;        // JSON string
  written_by: string;
  written_at: number;
  version: number;
}
