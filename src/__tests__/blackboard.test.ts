import { InMemoryBlackboard } from '../blackboard/InMemoryBlackboard.js';

describe('InMemoryBlackboard', () => {
  let bb: InMemoryBlackboard;

  beforeEach(() => {
    bb = new InMemoryBlackboard();
  });

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
});
