// ============================================================
// Maestro Protocol - Connection Store
// ============================================================
//
// SQLite-backed persistence for Connection membership.
// Survives process restarts so agents can resume Connections
// after going offline.
//
// Uses better-sqlite3 (synchronous API) for simplicity.
// ============================================================

import Database from 'better-sqlite3';
import { existsSync, mkdirSync } from 'fs';
import { dirname } from 'path';

// ----------------------------------------------------------
// Types
// ----------------------------------------------------------

export interface StoredConnection {
  connectionId: string;
  name: string;
  hostAgentId: string;
  hostEndpoint: string;
  myRole: string;
  status: 'active' | 'closed';
  joinedAt: number;
  expiresAt?: number;
}

// ----------------------------------------------------------
// ConnectionStore
// ----------------------------------------------------------

export class ConnectionStore {
  private db: Database.Database;

  constructor(private dbPath: string = '.maestro/connections.db') {
    const dir = dirname(dbPath);
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }
    this.db = new (Database as unknown as new (path: string) => Database.Database)(dbPath);
    this.init();
  }

  // ----------------------------------------------------------
  // Schema
  // ----------------------------------------------------------

  private init(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS connections (
        connection_id TEXT PRIMARY KEY,
        name          TEXT NOT NULL,
        host_agent_id TEXT NOT NULL,
        host_endpoint TEXT NOT NULL,
        my_role       TEXT NOT NULL,
        status        TEXT NOT NULL,
        joined_at     INTEGER NOT NULL,
        expires_at    INTEGER
      )
    `);
  }

  // ----------------------------------------------------------
  // Write
  // ----------------------------------------------------------

  save(connection: StoredConnection): void {
    this.db.prepare(`
      INSERT OR REPLACE INTO connections
        (connection_id, name, host_agent_id, host_endpoint, my_role, status, joined_at, expires_at)
      VALUES
        (@connectionId, @name, @hostAgentId, @hostEndpoint, @myRole, @status, @joinedAt, @expiresAt)
    `).run({
      connectionId:  connection.connectionId,
      name:          connection.name,
      hostAgentId:   connection.hostAgentId,
      hostEndpoint:  connection.hostEndpoint,
      myRole:        connection.myRole,
      status:        connection.status,
      joinedAt:      connection.joinedAt,
      expiresAt:     connection.expiresAt ?? null,
    });
  }

  close(connectionId: string): void {
    this.db.prepare(
      `UPDATE connections SET status = 'closed' WHERE connection_id = ?`,
    ).run(connectionId);
  }

  delete(connectionId: string): void {
    this.db.prepare(
      `DELETE FROM connections WHERE connection_id = ?`,
    ).run(connectionId);
  }

  /**
   * Close the underlying SQLite connection.
   * Call this before deleting the db file in tests or on process exit.
   */
  destroy(): void {
    this.db.close();
  }

  // ----------------------------------------------------------
  // Read
  // ----------------------------------------------------------

  get(connectionId: string): StoredConnection | undefined {
    const row = this.db.prepare(
      `SELECT * FROM connections WHERE connection_id = ?`,
    ).get(connectionId) as Record<string, unknown> | undefined;
    return row ? this.rowToConnection(row) : undefined;
  }

  list(): StoredConnection[] {
    const rows = this.db.prepare(`SELECT * FROM connections`).all() as Record<string, unknown>[];
    return rows.map(r => this.rowToConnection(r));
  }

  listActive(): StoredConnection[] {
    const rows = this.db.prepare(
      `SELECT * FROM connections WHERE status = 'active'`,
    ).all() as Record<string, unknown>[];
    return rows.map(r => this.rowToConnection(r));
  }

  // ----------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------

  private rowToConnection(row: Record<string, unknown>): StoredConnection {
    return {
      connectionId:  row['connection_id'] as string,
      name:          row['name'] as string,
      hostAgentId:   row['host_agent_id'] as string,
      hostEndpoint:  row['host_endpoint'] as string,
      myRole:        row['my_role'] as string,
      status:        row['status'] as 'active' | 'closed',
      joinedAt:      row['joined_at'] as number,
      ...(row['expires_at'] != null ? { expiresAt: row['expires_at'] as number } : {}),
    };
  }
}
