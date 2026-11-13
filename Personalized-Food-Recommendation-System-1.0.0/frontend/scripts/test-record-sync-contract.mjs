import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createRecordSyncQueueStore,
  parseRecordSyncQueue,
  canRetryPendingRecordSync,
  getPendingRecordReplayMetadata,
  LEGACY_RECORD_SYNC_QUEUE_KEY as OLD,
  RECORD_SYNC_QUEUE_KEY as KEY,
} from '../lib/record-sync-contract.ts';

const firstTime = '2026-11-13T23:50:00+08:00';
const nextDay = '2026-11-14T08:00:00+08:00';
const options = { legacyMealType: () => '晚餐' };
const food = { id: 'item-legacy', foodName: 'legacy', nutrition: { calories: 10, sodium: 0 }, estimatedWeight: undefined };
const legacy = (overrides = {}) => ({
  id: 'pending-one', userId: 'user-one', clientRecordId: 'client-one', foods: [food],
  source: 'camera', error: 'offline', attempts: 0, createdAt: firstTime, updatedAt: firstTime, ...overrides,
});
const payload = (overrides = {}) => ({
  nutrition_contract_version: 2, user_id: 'user-one', client_record_id: 'v2-one',
  timestamp: firstTime, meal_type: '晚餐', source: 'camera',
  foods: [{ item_id: 'server-item-1', name: 'unknown', weight_g: null, portion_source: 'unknown',
    included: true, user_entered_nutrients: { calories: null, protein: 0, carbs: null, fat: null,
      sugar: { value: '0.1', comparison: 'less_than', unit: 'g' }, sodium: null,
      fiber: null, saturated_fat: null, trans_fat: null } }],
  nutrition_context: { scan_id: 'server-scan-1', recognition_context: { revision: 2, items: [{ item_id: 'server-item-1' }] } },
  ...overrides,
});

function setup(initial = {}) {
  const data = new Map(Object.entries(initial));
  const events = [];
  let clock = firstTime;
  let counter = 0;
  const storage = {
    async getItem(key) { events.push(['get', key]); await Promise.resolve(); return data.get(key) ?? null; },
    async setItem(key, value) { events.push(['set', key]); data.set(key, value); },
    async removeItem(key) { events.push(['remove', key]); data.delete(key); },
  };
  const store = createRecordSyncQueueStore(storage, { ...options, now: () => clock, newId: () => `new-${++counter}` });
  return { data, events, storage, store, setClock: (value) => { clock = value; } };
}
function hasCode(code) { return (error) => error?.code === code; }

test('legacy migration freezes original queue time and meal, without nutrition metadata invention', async () => {
  const { store, data, events, setClock } = setup({ [OLD]: JSON.stringify([legacy()]) });
  setClock(nextDay);
  const [entry] = await store.loadLegacy();
  assert.equal(entry.nutritionContractVersion, 1);
  assert.equal(entry.recordTimestamp, firstTime);
  assert.equal(entry.mealType, '晚餐');
  assert.deepEqual(entry.foods, JSON.parse(JSON.stringify([food])));
  assert.equal('payload' in entry, false);
  assert.equal('nutrition_profile' in entry.foods[0], false);
  assert.equal(data.has(OLD), false);
  assert.ok(events.findIndex(([op]) => op === 'set') < events.findIndex(([op]) => op === 'remove'));
  assert.equal(JSON.parse(data.get(KEY)).queue_schema_version, 2);
});

test('migration write failure preserves old data and can be retried', async () => {
  const { storage, store, data } = setup({ [OLD]: JSON.stringify([legacy()]) });
  const normalWrite = storage.setItem;
  storage.setItem = async () => { throw new Error('quota full'); };
  await assert.rejects(() => store.loadLegacy(), /quota full/);
  assert.equal(data.has(OLD), true);
  assert.equal(data.has(KEY), false);
  storage.setItem = normalWrite;
  assert.equal((await store.loadLegacy()).length, 1);
});

test('malformed and future queues are retained and cannot be overwritten by enqueue or save', async () => {
  for (const raw of ['{', JSON.stringify({ queue_schema_version: 3, entries: [] }), JSON.stringify({ queue_schema_version: 2, entries: [legacy()] })]) {
    const { store, data, events } = setup({ [KEY]: raw });
    await assert.rejects(() => store.loadAll());
    await assert.rejects(() => store.enqueueLegacy({ userId: 'a', clientRecordId: 'b', foods: [], source: 'manual', error: '' }));
    await assert.rejects(() => store.saveLegacy([]));
    assert.equal(data.get(KEY), raw);
    assert.equal(events.some(([op]) => op === 'set' || op === 'remove'), false);
  }
});

test('invalid legacy entries are not silently dropped or deleted', async () => {
  const raw = JSON.stringify([legacy(), legacy({ id: 'bad', createdAt: 'no timezone' })]);
  const { store, data } = setup({ [OLD]: raw });
  await assert.rejects(() => store.loadAll(), hasCode('invalid_queue'));
  assert.equal(data.get(OLD), raw);
  assert.equal(data.has(KEY), false);
});

test('v2 roundtrip preserves null, exact zero, bound, source context and server identities', async () => {
  const { store } = setup();
  const original = payload();
  await store.enqueueV2(original, 'offline');
  const [entry] = await store.loadAll();
  assert.deepEqual(entry.payload, original);
  assert.equal(entry.nutritionContractVersion, 2);
  assert.equal((await store.loadLegacy()).length, 0);
});

test('enqueue captures an immutable snapshot before asynchronous writes and reads return deep copies', async () => {
  const { store } = setup();
  const original = payload();
  const pending = store.enqueueV2(original, 'offline');
  original.foods[0].name = 'changed by caller';
  await pending;
  const [entry] = await store.loadAll();
  assert.equal(entry.payload.foods[0].name, 'unknown');
  entry.payload.foods[0].weight_g = 999;
  assert.equal((await store.loadAll())[0].payload.foods[0].weight_g, null);
});

test('same-runtime concurrent enqueues retain both records', async () => {
  const { store } = setup();
  await Promise.all([
    store.enqueueV2(payload({ client_record_id: 'one' }), 'offline'),
    store.enqueueV2(payload({ client_record_id: 'two' }), 'offline'),
    store.enqueueLegacy({ userId: 'user-one', clientRecordId: 'three', foods: [food], source: 'manual', error: '' }),
  ]);
  assert.deepEqual((await store.loadAll()).map((entry) => entry.clientRecordId), ['one', 'two', 'three']);
});

test('duplicate v2 enqueue updates error only and rejects changed identity snapshot or version', async () => {
  const { store, setClock } = setup();
  await store.enqueueV2(payload(), 'first');
  const original = (await store.loadAll())[0];
  setClock(nextDay);
  await store.enqueueV2(payload(), 'second');
  const [retried] = await store.loadAll();
  assert.equal(retried.id, original.id);
  assert.equal(retried.createdAt, firstTime);
  assert.equal(retried.updatedAt, nextDay);
  assert.equal(retried.recordTimestamp, firstTime);
  assert.equal(retried.error, 'second');
  await assert.rejects(() => store.enqueueV2(payload({ timestamp: nextDay }), 'third'), hasCode('payload_conflict'));
  await assert.rejects(() => store.enqueueLegacy({ userId: 'user-one', clientRecordId: 'v2-one', foods: [], source: 'camera', error: '' }), hasCode('version_conflict'));
  assert.equal((await store.loadAll()).length, 1);
});

test('legacy writers and removal paths preserve v2 records', async () => {
  const { store } = setup();
  await store.enqueueV2(payload(), 'offline');
  await store.enqueueLegacy({ userId: 'user-one', clientRecordId: 'legacy', foods: [food], source: 'manual', error: '' });
  const [old] = await store.loadLegacy();
  await store.failLegacy(old.id, 'still offline');
  assert.equal((await store.loadLegacy())[0].attempts, 1);
  await store.saveLegacy([]);
  assert.equal((await store.loadAll()).length, 1);
  const [v2] = await store.loadAll();
  await store.removeLegacy(v2.id);
  await store.removeLegacyByClientId(v2.userId, v2.clientRecordId);
  assert.equal((await store.loadAll()).length, 1);
  await assert.rejects(() => store.saveLegacy([v2]), hasCode('version_conflict'));
});

test('v2 retries retain original time across midnight and preserve payload at the retry limit', async () => {
  const { store, setClock } = setup();
  await store.enqueueV2(payload(), 'offline');
  const [entry] = await store.loadAll();
  setClock(nextDay);
  for (let attempt = 0; attempt < 5; attempt++) await store.failV2(entry.id, 'retry failed');
  const [failed] = await store.loadAll();
  assert.equal(failed.attempts, 5);
  assert.equal(canRetryPendingRecordSync(failed), false);
  assert.equal(failed.recordTimestamp, firstTime);
  assert.deepEqual(failed.payload, payload());
  assert.equal(canRetryPendingRecordSync({ attempts: NaN }), false);
  await store.removeV2(entry.id);
  assert.equal((await store.loadAll()).length, 0);
});

test('timezone-less v2 payloads and nonfinite values cannot enter storage', async () => {
  const { store, data } = setup();
  await assert.rejects(() => store.enqueueV2(payload({ timestamp: '2026-11-13T23:50:00' }), 'offline'), hasCode('invalid_queue'));
  assert.throws(() => store.enqueueV2(payload({ foods: [{ weight_g: Infinity }] }), 'offline'), hasCode('invalid_queue'));
  assert.equal(data.has(KEY), false);
});

test('stored duplicate IDs and versions are rejected', () => {
  const old = legacy();
  assert.throws(() => parseRecordSyncQueue(JSON.stringify([old, old]), options, true), hasCode('invalid_queue'));
  assert.throws(() => parseRecordSyncQueue(JSON.stringify([legacy({ nutritionContractVersion: 2 })]), options, true), hasCode('invalid_queue'));
});

test('v2 queue refuses snapshots, forged source, duplicate food IDs and malformed create foods', async () => {
  for (const foods of [
    [{ ...payload().foods[0], nutrition_profile: null }],
    [{ ...payload().foods[0], source: 'TFDA' }],
    [{ ...payload().foods[0], nutrition_intake: {} }],
    [payload().foods[0], payload().foods[0]],
    [{ ...payload().foods[0], food_key: 'TFDA1' }],
    [{ ...payload().foods[0], weight_g: 0 }],
    [{ ...payload().foods[0], included: false }],
    [{ ...payload().foods[0], portion_source: ['unknown'] }],
    [{ ...payload().foods[0], user_entered_nutrients: {} }],
    [],
  ]) {
    const { store, data } = setup();
    await assert.rejects(() => store.enqueueV2(payload({ foods }), 'offline'), hasCode('invalid_queue'));
    assert.equal(data.has(KEY), false);
  }
});

test('legacy replay metadata uses frozen event time and meal, not created time or retry time', async () => {
  const { store, setClock } = setup();
  await store.enqueueLegacy({ userId: 'user-one', clientRecordId: 'delayed-save', foods: [food], source: 'camera',
    error: 'offline', recordTimestamp: '2026-11-13T08:30:00+08:00', mealType: '早餐' });
  setClock(nextDay);
  const [entry] = await store.loadLegacy();
  assert.equal(entry.createdAt, firstTime);
  assert.deepEqual(getPendingRecordReplayMetadata(entry), { timestamp: '2026-11-13T08:30:00+08:00', mealType: '早餐' });
  await store.failLegacy(entry.id, 'offline again');
  assert.deepEqual(getPendingRecordReplayMetadata((await store.loadLegacy())[0]), { timestamp: '2026-11-13T08:30:00+08:00', mealType: '早餐' });
});

test('reappearing legacy data after migration blocks reads and mutations without ignoring either queue', async () => {
  const { store, data, events } = setup();
  await store.enqueueV2(payload(), 'offline');
  const current = data.get(KEY);
  const old = JSON.stringify([legacy()]);
  data.set(OLD, old);
  events.length = 0;
  await assert.rejects(() => store.loadAll(), hasCode('mixed_queue_versions'));
  await assert.rejects(() => store.loadLegacy(), hasCode('mixed_queue_versions'));
  await assert.rejects(() => store.saveLegacy([]), hasCode('mixed_queue_versions'));
  await assert.rejects(() => store.removeV2('new-1'), hasCode('mixed_queue_versions'));
  assert.equal(data.get(KEY), current);
  assert.equal(data.get(OLD), old);
  assert.equal(events.some(([op]) => op === 'set' || op === 'remove'), false);
});

test('legacy snapshot changes during migration are retained alongside the initial v2 snapshot', async () => {
  const { store, data, storage } = setup({ [OLD]: JSON.stringify([legacy()]) });
  const write = storage.setItem;
  const concurrentLegacy = JSON.stringify([legacy(), legacy({ id: 'old-tab-new', clientRecordId: 'new-old-client' })]);
  storage.setItem = async (key, value) => {
    await write(key, value);
    if (key === KEY) data.set(OLD, concurrentLegacy);
  };
  await assert.rejects(() => store.loadAll(), hasCode('mixed_queue_versions'));
  assert.equal(data.get(OLD), concurrentLegacy);
  assert.equal(JSON.parse(data.get(KEY)).entries.length, 1);
});
