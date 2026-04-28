import { tmpdir } from 'os';
import { join } from 'path';
import { unlinkSync, existsSync } from 'fs';
import { SQLiteBlackboard } from '../blackboard/SQLiteBlackboard.js';

/** Generate a unique temp DB path for each test run */
function tmpDb(): string {
  return join(tmpdir(), `maestro-test-${Date.now()}-${Math.random().toString(36).slice(2)}.db`);
}

describe('SQLiteBlackboard', () => {
  let dbPath: string;
  let bb: SQLiteBlackboard;

  beforeEach(() => {
    dbPath = tmpDb();
    bb = new SQLiteBlackboard('conn-1', dbPath);
  });

  afterEach(() => {
    bb.close();
    if (existsSync(dbPath)) unlinkSync(dbPath);
    // WAL journal files
    const wal = dbPath + '-wal';
    const shm = dbPath + '-shm';
    if (existsSync(wal)) unlinkSync(wal);
    if (existsSync(shm)) unlinkSync(shm);
  });

  // ----------------------------------------------------------
  // Core read/write (mirrors blackboard.test.ts)
  // ----------------------------------------------------------

  it('sets and gets a value', async () => {
    await bb.set('status', { phase: 'design' }, 'Alpha');
    expect(await bb.get('status')).toEqual({ phase: 'design' });
  });

  it('returns undefined for missing key', async () => {
    expect(await bb.get('nonexistent')).toBeUndefined();
  });

  it('overwrites existing value (last-write-wins)', async () => {
    await bb.set('key', 'first', 'Alpha');
    await bb.set('key', 'second', 'Beta');
    expect(await bb.get('key')).toBe('second');
  });

  it('increments version on each write', async () => {
    await bb.set('key', 'v1', 'Alpha');
    await bb.set('key', 'v2', 'Alpha');
    const entry = await bb.getEntry('key');
    expect(entry?.version).toBe(2);
  });

  it('records who wrote the entry', async () => {
    await bb.set('key', 'val', 'Beta');
    const entry = await bb.getEntry('key');
    expect(entry?.writtenBy).toBe('Beta');
  });

  it('lists all keys', async () => {
    await bb.set('a', 1, 'Alpha');
    await bb.set('b', 2, 'Alpha');
    await bb.set('c', 3, 'Alpha');
    const keys = await bb.list();
    expect(keys).toContain('a');
    expect(keys).toContain('b');
    expect(keys).toContain('c');
  });

  it('lists keys by prefix', async () => {
    await bb.set('task:1', 1, 'Alpha');
    await bb.set('task:2', 2, 'Alpha');
    await bb.set('meta:1', 3, 'Alpha');
    const keys = await bb.list('task:');
    expect(keys).toContain('task:1');
    expect(keys).toContain('task:2');
    expect(keys).not.toContain('meta:1');
  });

  it('deletes a key', async () => {
    await bb.set('key', 'val', 'Alpha');
    await bb.delete('key', 'Alpha');
    expect(await bb.get('key')).toBeUndefined();
  });

  it('ignores delete of nonexistent key', async () => {
    await expect(bb.delete('ghost', 'Alpha')).resolves.not.toThrow();
  });

  it('notifies subscriber on set', async () => {
    const received: unknown[] = [];
    bb.subscribe('watched', (entry) => received.push(entry.value));
    await bb.set('watched', 'hello', 'Alpha');
    expect(received).toHaveLength(1);
    expect(received[0]).toBe('hello');
  });

  it('does not notify subscriber for different key', async () => {
    const received: unknown[] = [];
    bb.subscribe('watched', (entry) => received.push(entry.value));
    await bb.set('other', 'hello', 'Alpha');
    expect(received).toHaveLength(0);
  });

  it('notifies subscribeAll on any write', async () => {
    const keys: string[] = [];
    bb.subscribeAll((entry) => keys.push(entry.key));
    await bb.set('a', 1, 'Alpha');
    await bb.set('b', 2, 'Alpha');
    expect(keys).toContain('a');
    expect(keys).toContain('b');
  });

  it('unsubscribes correctly', async () => {
    const received: unknown[] = [];
    const unsub = bb.subscribe('key', (entry) => received.push(entry.value));
    await bb.set('key', 'before', 'Alpha');
    unsub();
    await bb.set('key', 'after', 'Alpha');
    expect(received).toHaveLength(1);
    expect(received[0]).toBe('before');
  });

  it('notifies on delete (tombstone)', async () => {
    const received: Array<unknown> = [];
    bb.subscribe('key', (entry) => received.push(entry.value));
    await bb.set('key', 'val', 'Alpha');
    await bb.delete('key', 'Alpha');
    expect(received).toHaveLength(2);
    expect(received[1]).toBeUndefined(); // tombstone
  });

  it('takes a snapshot', async () => {
    await bb.set('x', 1, 'Alpha');
    await bb.set('y', 2, 'Beta');
    const snap = await bb.snapshot();
    expect(snap['x'].value).toBe(1);
    expect(snap['y'].writtenBy).toBe('Beta');
  });

  it('clears all entries', async () => {
    await bb.set('a', 1, 'Alpha');
    await bb.set('b', 2, 'Alpha');
    await bb.clear();
    expect(await bb.list()).toHaveLength(0);
  });

  // ----------------------------------------------------------
  // Connection ID namespacing
  // ----------------------------------------------------------

  it('namespaces entries by connectionId', async () => {
    const bb2 = new SQLiteBlackboard('conn-2', dbPath);
    try {
      await bb.set('shared-key', 'from-conn-1', 'Alpha');
      await bb2.set('shared-key', 'from-conn-2', 'Beta');

      expect(await bb.get('shared-key')).toBe('from-conn-1');
      expect(await bb2.get('shared-key')).toBe('from-conn-2');
    } finally {
      bb2.close();
    }
  });

  // ----------------------------------------------------------
  // Persistence — survives restart
  // ----------------------------------------------------------

  it('persists data across instances (survives restart)', async () => {
    await bb.set('persistent-key', { hello: 'world' }, 'Alpha');
    await bb.set('another', 42, 'Beta');
    bb.close();

    // Open a new instance pointing at the same file
    const bb2 = new SQLiteBlackboard('conn-1', dbPath);
    try {
      expect(await bb2.get('persistent-key')).toEqual({ hello: 'world' });
      expect(await bb2.get('another')).toBe(42);
    } finally {
      bb2.close();
    }

    // Re-open original for afterEach cleanup
    bb = new SQLiteBlackboard('conn-1', dbPath);
  });

  it('persists version counters across instances', async () => {
    await bb.set('key', 'v1', 'Alpha');
    await bb.set('key', 'v2', 'Alpha');
    const v1 = (await bb.getEntry('key'))!.version;
    bb.close();

    const bb2 = new SQLiteBlackboard('conn-1', dbPath);
    try {
      await bb2.set('key', 'v3', 'Alpha');
      const v2 = (await bb2.getEntry('key'))!.version;
      expect(v2).toBe(v1 + 1); // Version continues from where we left off
    } finally {
      bb2.close();
    }

    bb = new SQLiteBlackboard('conn-1', dbPath);
  });

  // ----------------------------------------------------------
  // Cross-process apply (applyRemoteUpdate)
  // ----------------------------------------------------------

  it('applies a remote update when version is newer', async () => {
    await bb.set('key', 'local', 'Alpha'); // version 1
    const remoteEntry = {
      key: 'key',
      value: 'remote',
      writtenBy: 'Beta',
      writtenAt: Date.now(),
      version: 2, // newer
    };
    bb.applyRemoteUpdate(remoteEntry);
    expect(await bb.get('key')).toBe('remote');
  });

  it('ignores stale remote update (version not newer)', async () => {
    await bb.set('key', 'local-v2', 'Alpha');
    await bb.set('key', 'local-v3', 'Alpha'); // version 2 now
    const staleEntry = {
      key: 'key',
      value: 'stale',
      writtenBy: 'Beta',
      writtenAt: Date.now() - 5000,
      version: 1, // older
    };
    bb.applyRemoteUpdate(staleEntry);
    expect(await bb.get('key')).toBe('local-v3'); // unchanged
  });

  it('emits in-process event when remote update is applied', async () => {
    const received: unknown[] = [];
    bb.subscribe('key', (entry) => received.push(entry.value));

    bb.applyRemoteUpdate({
      key: 'key',
      value: 'from-remote',
      writtenBy: 'Beta',
      writtenAt: Date.now(),
      version: 1,
    });

    expect(received).toHaveLength(1);
    expect(received[0]).toBe('from-remote');
  });

  it('applies remote delete (tombstone) when version is newer', async () => {
    await bb.set('key', 'val', 'Alpha'); // version 1
    bb.applyRemoteUpdate({
      key: 'key',
      value: undefined,
      writtenBy: 'Beta',
      writtenAt: Date.now(),
      version: 2,
    });
    expect(await bb.get('key')).toBeUndefined();
  });
});
