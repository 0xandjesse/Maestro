// ============================================================
// Maestro Protocol — SQLite Blackboard
// ============================================================
//
// Persistent drop-in replacement for InMemoryBlackboard.
// Uses better-sqlite3 (synchronous) wrapped in async methods
// to match the SharedBlackboard interface.
//
// Schema: bb_entries (key, connection_id, value, written_by,
//                     written_at, version)
//
// - connectionId namespaces entries per Venue/Connection.
// - value is JSON-serialized.
// - version is monotonically increasing per (key, connection_id).
// - In-process pub/sub via EventEmitter (same pattern as
//   InMemoryBlackboard) for same-process subscribers.
//
// Default DB path: .maestro/blackboard.db
// ============================================================

import { EventEmitter } from 'events';
import { mkdirSync, existsSync } from 'fs';
import { dirname } from 'path';
import Database from 'better-sqlite3';
import {
  BlackboardEntry,
  SharedBlackboard,
  Unsubscribe,
} from './types.js';

// Row shape returned from SQLite
interface DbRow {
  key: string;
  connection_id: string;
  value: string;
  written_by: string;
  written_at: number;
  version: number;
}

export class SQLiteBlackboard extends EventEmitter implements SharedBlackboard {
  private db: Database.Database;

  constructor(
    private stageId: string,
    private dbPath: string = '.maestro/blackboard.db',
  ) {
    super();

    // Ensure directory exists
    const dir = dirname(this.dbPath);
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }

    this.db = new Database(this.dbPath);
    this.db.pragma('journal_mode = WAL');  // Better concurrent read performance
    this.db.pragma('synchronous = NORMAL');
    this.initSchema();
  }

  // ----------------------------------------------------------
  // Schema
  // ----------------------------------------------------------

  private initSchema(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS bb_entries (
        key           TEXT    NOT NULL,
        connection_id TEXT    NOT NULL,
        value         TEXT    NOT NULL,
        written_by    TEXT    NOT NULL,
        written_at    INTEGER NOT NULL,
        version       INTEGER NOT NULL,
        PRIMARY KEY (key, connection_id)
      );
    `);
  }

  // ----------------------------------------------------------
  // Read
  // ----------------------------------------------------------

  async get(key: string): Promise<unknown> {
    const row = this.db
      .prepare<[string, string]>('SELECT value FROM bb_entries WHERE key = ? AND connection_id = ?')
      .get(key, this.stageId) as Pick<DbRow, 'value'> | undefined;

    if (!row) return undefined;
    return JSON.parse(row.value);
  }

  async getEntry(key: string): Promise<BlackboardEntry | undefined> {
    const row = this.db
      .prepare<[string, string]>(
        'SELECT key, value, written_by, written_at, version FROM bb_entries WHERE key = ? AND connection_id = ?',
      )
      .get(key, this.stageId) as DbRow | undefined;

    if (!row) return undefined;
    return this.rowToEntry(row);
  }

  async list(prefix?: string): Promise<string[]> {
    let rows: Array<{ key: string }>;
    if (prefix) {
      rows = this.db
        .prepare<[string, string]>(
          "SELECT key FROM bb_entries WHERE connection_id = ? AND key LIKE ? ESCAPE '\\'",
        )
        .all(this.stageId, this.escapeLike(prefix) + '%') as Array<{ key: string }>;
    } else {
      rows = this.db
        .prepare<[string]>('SELECT key FROM bb_entries WHERE connection_id = ?')
        .all(this.stageId) as Array<{ key: string }>;
    }
    return rows.map(r => r.key);
  }

  // ----------------------------------------------------------
  // Write
  // ----------------------------------------------------------

  async set(key: string, value: unknown, writtenBy: string): Promise<void> {
    const version = this.nextVersion(key);
    const writtenAt = Date.now();
    const serialized = JSON.stringify(value);

    this.db
      .prepare<[string, string, string, string, number, number]>(`
        INSERT INTO bb_entries (key, connection_id, value, written_by, written_at, version)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (key, connection_id) DO UPDATE SET
          value      = excluded.value,
          written_by = excluded.written_by,
          written_at = excluded.written_at,
          version    = excluded.version
      `)
      .run(key, this.stageId, serialized, writtenBy, writtenAt, version);

    const entry: BlackboardEntry = { key, value, writtenBy, writtenAt, version };
    this.emit(`key:${key}`, entry);
    this.emit('*', entry);
  }

  async delete(key: string, writtenBy: string): Promise<void> {
    const existing = this.db
      .prepare<[string, string]>(
        'SELECT version FROM bb_entries WHERE key = ? AND connection_id = ?',
      )
      .get(key, this.stageId) as Pick<DbRow, 'version'> | undefined;

    if (!existing) return;

    const version = existing.version + 1;
    const writtenAt = Date.now();

    this.db
      .prepare<[string, string]>('DELETE FROM bb_entries WHERE key = ? AND connection_id = ?')
      .run(key, this.stageId);

    // Emit tombstone so subscribers are notified
    const tombstone: BlackboardEntry = {
      key,
      value: undefined,
      writtenBy,
      writtenAt,
      version,
    };
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
    this.db
      .prepare<[string]>('DELETE FROM bb_entries WHERE connection_id = ?')
      .run(this.stageId);
  }

  async snapshot(): Promise<Record<string, BlackboardEntry>> {
    const rows = this.db
      .prepare<[string]>(
        'SELECT key, value, written_by, written_at, version FROM bb_entries WHERE connection_id = ?',
      )
      .all(this.stageId) as DbRow[];

    const result: Record<string, BlackboardEntry> = {};
    for (const row of rows) {
      result[row.key] = this.rowToEntry(row);
    }
    return result;
  }

  /** Close the underlying DB connection (call on graceful shutdown). */
  close(): void {
    this.db.close();
  }

  // ----------------------------------------------------------
  // Cross-process apply (last-write-wins)
  // ----------------------------------------------------------

  /**
   * Apply an incoming update from another process.
   * Only applies if the incoming version > local version (last-write-wins).
   * Emits in-process pub/sub events so local subscribers are notified.
   */
  applyRemoteUpdate(entry: BlackboardEntry): void {
    const existing = this.db
      .prepare<[string, string]>(
        'SELECT version FROM bb_entries WHERE key = ? AND connection_id = ?',
      )
      .get(entry.key, this.stageId) as Pick<DbRow, 'version'> | undefined;

    const localVersion = existing?.version ?? 0;
    if (entry.version <= localVersion) return; // Stale — ignore

    if (entry.value === undefined) {
      // Tombstone — delete
      this.db
        .prepare<[string, string]>('DELETE FROM bb_entries WHERE key = ? AND connection_id = ?')
        .run(entry.key, this.stageId);
    } else {
      this.db
        .prepare<[string, string, string, string, number, number]>(`
          INSERT INTO bb_entries (key, connection_id, value, written_by, written_at, version)
          VALUES (?, ?, ?, ?, ?, ?)
          ON CONFLICT (key, connection_id) DO UPDATE SET
            value      = excluded.value,
            written_by = excluded.written_by,
            written_at = excluded.written_at,
            version    = excluded.version
        `)
        .run(
          entry.key,
          this.stageId,
          JSON.stringify(entry.value),
          entry.writtenBy,
          entry.writtenAt,
          entry.version,
        );
    }

    // Notify in-process subscribers
    this.emit(`key:${entry.key}`, entry);
    this.emit('*', entry);
  }

  // ----------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------

  private nextVersion(key: string): number {
    const row = this.db
      .prepare<[string, string]>(
        'SELECT version FROM bb_entries WHERE key = ? AND connection_id = ?',
      )
      .get(key, this.stageId) as Pick<DbRow, 'version'> | undefined;
    return (row?.version ?? 0) + 1;
  }

  private rowToEntry(row: DbRow): BlackboardEntry {
    return {
      key: row.key,
      value: JSON.parse(row.value),
      writtenBy: row.written_by,
      writtenAt: row.written_at,
      version: row.version,
    };
  }

  private escapeLike(s: string): string {
    return s.replace(/[%_\\]/g, c => '\\' + c);
  }
}
