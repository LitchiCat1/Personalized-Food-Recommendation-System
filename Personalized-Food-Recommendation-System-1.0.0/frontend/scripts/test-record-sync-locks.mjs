import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createRecordSyncQueueStore,
  createWebRecordSyncQueueLock,
  assertPendingRecordSyncTarget,
  LEGACY_RECORD_SYNC_QUEUE_KEY as OLD,
  RECORD_SYNC_QUEUE_KEY as KEY,
  RECORD_SYNC_QUEUE_LOCK_NAME,
} from '../lib/record-sync-contract.ts';

const firstTime = '2026-11-13T23:50:00+08:00';
const nextDay = '2026-11-14T08:00:00+08:00';
const legacyFood = { id: 'food', foodName: 'rice', nutrition: { calories: 100 } };
const payload = (id) => ({
  nutrition_contract_version: 2, user_id: 'user', client_record_id: id,
  timestamp: firstTime, meal_type: '晚餐', source: 'camera',
  foods: [{ item_id: 'unresolved', name: 'unknown', weight_g: null, portion_source: 'unknown' }],
});
const legacyParams = (id, extra = {}) => ({
  userId: 'user', clientRecordId: id, foods: [legacyFood], source: 'manual', error: 'offline', ...extra,
});
const oldEntry = {
  id: 'old-entry', userId: 'user', clientRecordId: 'old-record', foods: [legacyFood],
  source: 'manual', error: 'offline', attempts: 0, createdAt: firstTime, updatedAt: firstTime,
};
const hasCode = (code) => (error) => error?.code === code;

function setup(initial = {}) {
  const data = new Map(Object.entries(initial));
  const calls = [];
  const events = [];
  let tail = Promise.resolve();
  let active = 0;
  let counter = 0;
  let at = firstTime;
  const manager = {
    request(name, options, work) {
      calls.push([name, options]);
      const result = tail.then(async () => {
        active += 1;
        assert.equal(active, 1);
        try { return await work(); } finally { active -= 1; }
      });
      tail = result.catch(() => undefined);
      return result;
    },
  };
  const storage = {
    async getItem(key) {
      assert.equal(active, 1, 'even reads and migrations require the shared lock');
      events.push(['get', key]);
      await Promise.resolve();
      return data.get(key) ?? null;
    },
    async setItem(key, value) {
      assert.equal(active, 1);
      events.push(['set', key]);
      await Promise.resolve();
      data.set(key, value);
    },
    async removeItem(key) {
      assert.equal(active, 1);
      events.push(['remove', key]);
      await Promise.resolve();
      data.delete(key);
    },
  };
  const createStore = (lockManager = manager) => createRecordSyncQueueStore(storage, {
    legacyMealType: () => '晚餐', now: () => at, newId: () => `queue-${++counter}`,
    lock: createWebRecordSyncQueueLock(lockManager),
  });
  return { data, calls, events, storage, createStore, setClock(value) { at = value; } };
}

test('independent stores serialize concurrent v1 and v2 enqueues with the same exclusive lock', async () => {
  const fixture = setup();
  const first = fixture.createStore();
  const second = fixture.createStore();
  await Promise.all([
    first.enqueueV2(payload('first'), 'offline'),
    second.enqueueV2(payload('second'), 'offline'),
    second.enqueueLegacy(legacyParams('third')),
  ]);
  assert.deepEqual((await first.loadAll()).map((entry) => entry.clientRecordId), ['first', 'second', 'third']);
  assert.ok(fixture.calls.length >= 4);
  for (const [name, options] of fixture.calls) {
    assert.equal(name, RECORD_SYNC_QUEUE_LOCK_NAME);
    assert.deepEqual(options, { mode: 'exclusive' });
  }
});

test('concurrent retry failures do not lose increments or resurrect a removed record', async () => {
  const fixture = setup();
  const first = fixture.createStore();
  const second = fixture.createStore();
  await first.enqueueV2(payload('keep'), 'offline');
  await first.enqueueLegacy(legacyParams('remove'));
  const [keep, remove] = await first.loadAll();
  await Promise.all([
    first.failV2(keep.id, 'first failure'),
    second.failV2(keep.id, 'second failure'),
    second.removeLegacy(remove.id),
  ]);
  const entries = await first.loadAll();
  assert.equal(entries.length, 1);
  assert.equal(entries[0].attempts, 2);
  assert.equal(entries[0].error, 'second failure');
  assert.deepEqual(entries[0].payload, payload('keep'));
});

test('a migration racing a new enqueue migrates once and retains every record', async () => {
  const fixture = setup({ [OLD]: JSON.stringify([oldEntry]) });
  const first = fixture.createStore();
  const second = fixture.createStore();
  await Promise.all([first.loadLegacy(), second.enqueueV2(payload('new'), 'offline')]);
  assert.equal(fixture.data.has(OLD), false);
  assert.deepEqual((await second.loadAll()).map((entry) => entry.clientRecordId), ['old-record', 'new']);
  assert.equal(fixture.events.filter(([event]) => event === 'remove').length, 1);
  const writeIndex = fixture.events.findIndex(([event]) => event === 'set');
  const removeIndex = fixture.events.findIndex(([event]) => event === 'remove');
  assert.ok(writeIndex < removeIndex);
});

test('lock remains usable after queue validation and storage failures', async () => {
  const fixture = setup({ [KEY]: '{' });
  const first = fixture.createStore();
  const second = fixture.createStore();
  await assert.rejects(first.loadAll(), hasCode('invalid_queue'));
  fixture.data.delete(KEY);
  const write = fixture.storage.setItem;
  fixture.storage.setItem = async () => { throw new Error('quota full'); };
  await assert.rejects(second.enqueueV2(payload('first'), 'offline'), /quota full/);
  fixture.storage.setItem = write;
  await first.enqueueV2(payload('second'), 'offline');
  assert.equal((await second.loadAll())[0].clientRecordId, 'second');
});

test('unsupported web coordination fails before reading, writing or deleting either queue', async () => {
  for (const manager of [undefined, null, {}]) {
    const fixture = setup({ [OLD]: JSON.stringify([oldEntry]) });
    const queue = manager === undefined
      ? createRecordSyncQueueStore(fixture.storage, { legacyMealType: () => '晚餐', lock: createWebRecordSyncQueueLock() })
      : fixture.createStore(manager);
    await assert.rejects(queue.loadAll(), hasCode('storage_coordination_unavailable'));
    await assert.rejects(queue.enqueueV2(payload('new'), 'offline'), hasCode('storage_coordination_unavailable'));
    await assert.rejects(queue.saveLegacy([]), hasCode('storage_coordination_unavailable'));
    await assert.rejects(queue.removeLegacy('old-entry'), hasCode('storage_coordination_unavailable'));
    assert.deepEqual(fixture.events, []);
    assert.equal(fixture.data.get(OLD), JSON.stringify([oldEntry]));
    assert.equal(fixture.data.has(KEY), false);
  }
});

test('denied lock acquisition returns a typed coordination error without changing storage', async () => {
  const fixture = setup({ [OLD]: JSON.stringify([oldEntry]) });
  const queue = fixture.createStore({ request: async () => { throw new Error('denied'); } });
  await assert.rejects(queue.loadLegacy(), hasCode('storage_coordination_unavailable'));
  await assert.rejects(queue.enqueueLegacy(legacyParams('new')), hasCode('storage_coordination_unavailable'));
  assert.deepEqual(fixture.events, []);
  assert.equal(fixture.data.has(KEY), false);
});

test('mixed legacy and v2 keys still refuse reconciliation under the lock and retain both snapshots', async () => {
  const current = JSON.stringify({ queue_schema_version: 2, entries: [] });
  const old = JSON.stringify([oldEntry]);
  const fixture = setup({ [KEY]: current, [OLD]: old });
  await assert.rejects(fixture.createStore().loadAll(), hasCode('mixed_queue_versions'));
  await assert.rejects(fixture.createStore().enqueueV2(payload('new'), 'offline'), hasCode('mixed_queue_versions'));
  assert.equal(fixture.data.get(KEY), current);
  assert.equal(fixture.data.get(OLD), old);
  assert.equal(fixture.events.some(([event]) => event === 'set' || event === 'remove'), false);
});

test('explicit legacy event time and meal cannot change under the same client identity', async () => {
  const fixture = setup();
  const first = fixture.createStore();
  const second = fixture.createStore();
  const frozen = { recordTimestamp: firstTime, mealType: '晚餐' };
  await first.enqueueLegacy(legacyParams('same', frozen));
  fixture.setClock(nextDay);
  await assert.rejects(second.enqueueLegacy(legacyParams('same', { ...frozen, recordTimestamp: nextDay })), hasCode('payload_conflict'));
  await assert.rejects(second.enqueueLegacy(legacyParams('same', { ...frozen, mealType: '早餐' })), hasCode('payload_conflict'));
  await second.enqueueLegacy(legacyParams('same'));
  const [entry] = await first.loadLegacy();
  assert.equal(entry.recordTimestamp, firstTime);
  assert.equal(entry.mealType, '晚餐');
  assert.equal(entry.createdAt, firstTime);
  assert.equal(entry.updatedAt, nextDay);
});

test('v1 and v2 queues retain the exact backend target outside the immutable request payload', async () => {
  const fixture = setup();
  const store = fixture.createStore();
  const target = 'https://API.example.test:443/nutrition/';
  await store.enqueueLegacy(legacyParams('legacy-bound', { apiBaseUrl: target }));
  await store.enqueueV2(payload('v2-bound'), 'offline', target);
  const entries = await store.loadAll();
  assert.deepEqual(entries.map((entry) => entry.apiBaseUrl), [target, target]);
  assert.equal('apiBaseUrl' in entries[1].payload, false);
  assert.deepEqual(entries[1].payload, payload('v2-bound'));
  await store.enqueueLegacy(legacyParams('legacy-bound'));
  await store.enqueueV2(payload('v2-bound'), 'retry');
  for (const entry of await store.loadAll()) assertPendingRecordSyncTarget(entry, target);
});

test('target verification never reads or changes storage and blocks absent or different targets', async () => {
  const fixture = setup({ [OLD]: JSON.stringify([oldEntry]) });
  const original = fixture.data.get(OLD);
  assert.throws(() => assertPendingRecordSyncTarget({}, 'https://api.example.test'), hasCode('target_unverified'));
  assert.throws(() => assertPendingRecordSyncTarget({ apiBaseUrl: 'https://first.example.test' }, 'https://second.example.test'), hasCode('target_mismatch'));
  assert.throws(() => assertPendingRecordSyncTarget({ apiBaseUrl: 'https://api.example.test/' }, 'https://api.example.test'), hasCode('target_mismatch'));
  assert.throws(() => assertPendingRecordSyncTarget({ apiBaseUrl: 'not-a-url' }, 'https://api.example.test'), hasCode('target_unverified'));
  assertPendingRecordSyncTarget({ apiBaseUrl: 'https://api.example.test' }, 'https://api.example.test');
  assert.deepEqual(fixture.events, []);
  assert.equal(fixture.data.get(OLD), original);
});

test('same client identity cannot change its backend or silently bind a previously unbound record', async () => {
  const fixture = setup();
  const store = fixture.createStore();
  await store.enqueueLegacy(legacyParams('legacy-bound', { apiBaseUrl: 'https://first.example.test' }));
  await store.enqueueV2(payload('v2-bound'), 'offline', 'https://first.example.test');
  await store.enqueueLegacy(legacyParams('legacy-unbound'));
  await store.enqueueV2(payload('v2-unbound'), 'offline');
  const before = fixture.data.get(KEY);
  fixture.events.length = 0;
  await assert.rejects(store.enqueueLegacy(legacyParams('legacy-bound', { apiBaseUrl: 'https://second.example.test' })), hasCode('payload_conflict'));
  await assert.rejects(store.enqueueV2(payload('v2-bound'), 'retry', 'https://second.example.test'), hasCode('payload_conflict'));
  await assert.rejects(store.enqueueLegacy(legacyParams('legacy-unbound', { apiBaseUrl: 'https://first.example.test' })), hasCode('payload_conflict'));
  await assert.rejects(store.enqueueV2(payload('v2-unbound'), 'retry', 'https://first.example.test'), hasCode('payload_conflict'));
  assert.equal(fixture.data.get(KEY), before);
  assert.equal(fixture.events.some(([event]) => event === 'set' || event === 'remove'), false);
});

test('invalid or credential-bearing backend targets are rejected before queue access', async () => {
  for (const target of ['', 'file:///tmp/queue', 'https://user:secret@example.test', 'https://user@example.test',
    ' https://api.example.test', 'https://api.example.test\n', 'not-a-url']) {
    const fixture = setup({ [OLD]: JSON.stringify([oldEntry]) });
    const store = fixture.createStore();
    assert.throws(() => store.enqueueLegacy(legacyParams('legacy', { apiBaseUrl: target })), hasCode('invalid_queue'));
    assert.throws(() => store.enqueueV2(payload('v2'), 'offline', target), hasCode('invalid_queue'));
    assert.deepEqual(fixture.events, []);
    assert.equal(fixture.data.has(KEY), false);
  }
});
