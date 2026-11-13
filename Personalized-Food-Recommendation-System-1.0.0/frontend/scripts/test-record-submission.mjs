import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { createRecordSubmissionSession } from '../lib/record-submission.ts';
import { assertPendingRecordSyncTarget, createRecordSyncQueueStore, getPendingRecordReplayMetadata } from '../lib/record-sync-contract.ts';
import { formatLocalTimestamp } from '../lib/dietary-records.ts';
import { getAutoMealType } from '../lib/meal.ts';
import { saveRecord } from '../lib/scanner.ts';

function food(overrides = {}) {
  return {
    id: 'food-one', foodName: 'Rice', confidence: 95, source: 'TFDA', needsConfirmation: false,
    boundingBox: { x: 0, y: 0, w: 0, h: 0 }, estimatedWeight: 150,
    nutrition: { calories: 183.75, protein: 4, carbs: 40, sugar: 0, fat: 1,
      saturated_fat: 0.2, trans_fat: 0, sodium: 0, fiber: 2, is_fried: false },
    gi: 'medium', allergens: [], warnings: [], ...overrides,
  };
}

function setup(t, initial = new Date(2026, 10, 13, 23, 59, 59)) {
  let clock = initial;
  let nextId = 0;
  let current = true;
  let failWrite = false;
  let failCleanup = false;
  let respond = async () => ({ ok: true, json: async () => ({}) });
  const data = new Map();
  const events = [];
  const posts = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    const body = JSON.parse(init.body);
    events.push('post');
    posts.push({ url, body, authorization: init.headers.Authorization });
    return respond(body);
  };
  t.after(() => { globalThis.fetch = originalFetch; });
  const storage = {
    async getItem(key) { return data.get(key) ?? null; },
    async setItem(key, value) {
      if (failWrite) throw new Error('storage unavailable');
      events.push('write');
      data.set(key, value);
    },
    async removeItem(key) { data.delete(key); },
  };
  const queue = createRecordSyncQueueStore(storage, {
    legacyMealType: (value) => getAutoMealType(new Date(value)),
    now: () => clock.toISOString(), newId: () => `pending-${++nextId}`,
  });
  const session = createRecordSubmissionSession({
    now: () => clock, newId: () => `client-${++nextId}`, mealType: getAutoMealType, timestamp: formatLocalTimestamp,
  });
  const params = {
    apiBaseUrl: 'https://api.example.test', userId: 'user-one', foods: [food()],
    source: 'camera', submissionKey: 'visible-draft-one',
  };
  const io = {
    isCurrent: () => current,
    persist: (request) => queue.enqueueLegacy({ userId: request.userId, clientRecordId: request.clientRecordId,
      foods: request.foods, source: request.source, recordTimestamp: request.timestamp,
      mealType: request.mealType, apiBaseUrl: request.apiBaseUrl, error: '' }),
    send: (request) => saveRecord({ ...request, auth: { accessToken: 'isolated-test-token' } }),
    remove: async (request) => {
      events.push('cleanup');
      if (failCleanup) throw new Error('cleanup unavailable');
      return queue.removeLegacyByClientId(request.userId, request.clientRecordId);
    },
  };
  return { session, queue, params, io, events, posts,
    setClock: (value) => { clock = value; },
    setCurrent: (value) => { current = value; },
    setFailWrite: (value) => { failWrite = value; },
    setFailCleanup: (value) => { failCleanup = value; },
    setRespond: (value) => { respond = value; },
  };
}

const hasCode = (code) => (error) => error?.code === code;

test('freezes event time and meal before a first request crosses midnight', async (t) => {
  const at = new Date(2026, 10, 13, 23, 59, 59);
  const state = setup(t, at);
  const request = state.session.prepare(state.params);
  state.setClock(new Date(2026, 10, 14, 0, 1));
  await state.session.deliver(request, state.io);
  assert.equal(state.posts[0].body.timestamp, formatLocalTimestamp(at));
  assert.equal(state.posts[0].body.meal_type, getAutoMealType(at));
  assert.ok(state.events.indexOf('write') < state.events.indexOf('post'));
  assert.equal((await state.queue.loadAll()).length, 0);
});

test('breakfast submitted before the meal boundary stays breakfast on later retry', async (t) => {
  const at = new Date(2026, 10, 13, 9, 59, 59);
  const state = setup(t, at);
  const request = state.session.prepare(state.params);
  state.setRespond(async () => { throw new Error('network failed'); });
  await assert.rejects(() => state.session.deliver(request, state.io), /network failed/);
  state.setClock(new Date(2026, 10, 13, 10, 1));
  state.setRespond(async () => ({ ok: true }));
  await state.session.deliver(state.session.prepare(state.params), state.io);
  assert.equal(state.posts[1].body.meal_type, getAutoMealType(at));
  assert.equal(state.posts[1].body.timestamp, formatLocalTimestamp(at));
  assert.deepEqual(state.posts[1].body, state.posts[0].body);
});

test('write-ahead storage failure prevents any POST and preserves the session event', async (t) => {
  const state = setup(t);
  const request = state.session.prepare(state.params);
  state.setFailWrite(true);
  await assert.rejects(() => state.session.deliver(request, state.io), /storage unavailable/);
  assert.equal(state.posts.length, 0);
  state.setClock(new Date(2026, 10, 14, 8));
  state.setFailWrite(false);
  await state.session.deliver(state.session.prepare(state.params), state.io);
  assert.equal(state.posts[0].body.timestamp, request.timestamp);
  assert.equal(state.posts[0].body.client_record_id, request.clientRecordId);
});

test('ambiguous remote success retries the exact full original body and idempotency ID', async (t) => {
  const state = setup(t);
  const savedOnServer = new Map();
  state.setRespond(async (body) => {
    savedOnServer.set(body.client_record_id, body);
    throw new Error('response connection lost');
  });
  const request = state.session.prepare(state.params);
  await assert.rejects(() => state.session.deliver(request, state.io), /connection lost/);
  const [queued] = await state.queue.loadLegacy();
  assertPendingRecordSyncTarget(queued, request.apiBaseUrl);
  assert.equal(queued.clientRecordId, request.clientRecordId);
  assert.deepEqual(getPendingRecordReplayMetadata(queued), { timestamp: request.timestamp, mealType: request.mealType });
  state.setClock(new Date(2026, 10, 14, 8));
  state.setRespond(async (body) => {
    assert.deepEqual(body, savedOnServer.get(body.client_record_id));
    return { ok: true };
  });
  await state.session.deliver(state.session.prepare(state.params), state.io);
  assert.deepEqual(state.posts[0].body, state.posts[1].body);
  assert.equal(savedOnServer.size, 1);
  assert.equal((await state.queue.loadAll()).length, 0);
});

test('editing a pending draft cannot send different food values under the same event ID', async (t) => {
  const state = setup(t);
  state.setRespond(async () => { throw new Error('offline'); });
  const request = state.session.prepare(state.params);
  await assert.rejects(() => state.session.deliver(request, state.io), /offline/);
  const edited = structuredClone(state.params);
  edited.foods[0].nutrition.calories = 999;
  assert.throws(() => state.session.prepare(edited), hasCode('submission_changed'));
  assert.equal(state.posts.length, 1);
  const [queued] = await state.queue.loadLegacy();
  assert.equal(queued.foods[0].nutrition.calories, 183.75);
});

test('caller mutations cannot alter the captured food cells or returned request', async (t) => {
  const state = setup(t);
  const request = state.session.prepare(state.params);
  state.params.foods[0].nutrition.calories = 999;
  request.foods[0].nutrition.calories = 888;
  await assert.rejects(() => state.session.deliver(request, state.io), hasCode('submission_changed'));
  assert.equal(state.posts.length, 0);
  const original = state.session.prepare({ ...state.params, foods: [food()] });
  await state.session.deliver(original, state.io);
  assert.equal(state.posts[0].body.foods[0].calories, 183.75);
});

test('local cleanup failure keeps a saved marker and a second click cannot resend', async (t) => {
  const state = setup(t);
  const request = state.session.prepare(state.params);
  state.setFailCleanup(true);
  const result = await state.session.deliver(request, state.io);
  assert.deepEqual(result, { alreadySaved: false, cleanupPending: true });
  assert.equal((await state.queue.loadAll()).length, 1);
  state.setFailCleanup(false);
  assert.deepEqual(await state.session.deliver(request, state.io), { alreadySaved: true, cleanupPending: false });
  assert.equal(state.posts.length, 1);
  assert.equal((await state.queue.loadAll()).length, 0);
});

test('automatic replay success marks a still-visible draft saved before queue cleanup', async (t) => {
  const state = setup(t);
  const request = state.session.prepare(state.params);
  state.setRespond(async () => { throw new Error('offline'); });
  await assert.rejects(() => state.session.deliver(request, state.io), /offline/);
  const [queued] = await state.queue.loadLegacy();
  state.setRespond(async () => ({ ok: true }));
  await saveRecord({ apiBaseUrl: request.apiBaseUrl, userId: queued.userId,
    clientRecordId: queued.clientRecordId, foods: queued.foods, source: queued.source,
    ...getPendingRecordReplayMetadata(queued) });
  state.session.markSaved(request.apiBaseUrl, queued.userId, queued.clientRecordId);
  const result = await state.session.deliver(state.session.prepare(state.params), state.io);
  assert.equal(result.alreadySaved, true);
  assert.equal(state.posts.length, 2);
  assert.equal((await state.queue.loadAll()).length, 0);
});

test('changing account retains the original queue and suppresses stale authorization effects', async (t) => {
  const state = setup(t);
  const request = state.session.prepare(state.params);
  const persist = state.io.persist;
  state.io.persist = async (snapshot) => {
    await persist(snapshot);
    state.setCurrent(false);
  };
  await assert.rejects(() => state.session.deliver(request, state.io), hasCode('submission_interrupted'));
  assert.equal(state.posts.length, 0);
  assert.equal((await state.queue.loadAll())[0].userId, 'user-one');

  const originalWindow = globalThis.window;
  let authorizationEvents = 0;
  let currentSession = true;
  globalThis.window = { dispatchEvent() { authorizationEvents += 1; } };
  t.after(() => { globalThis.window = originalWindow; });
  state.setRespond(async () => {
    currentSession = false;
    return { ok: false, status: 401, json: async () => ({ error: 'expired old session' }) };
  });
  await assert.rejects(() => saveRecord({ ...request, auth: { accessToken: 'old-token' },
    isCurrentSession: () => currentSession }), /expired old session/);
  assert.equal(authorizationEvents, 0);
  state.setRespond(async () => ({ ok: false, status: 401, json: async () => ({ error: 'expired current session' }) }));
  currentSession = true;
  await assert.rejects(() => saveRecord({ ...request, auth: { accessToken: 'current-token' },
    isCurrentSession: () => currentSession }), /expired current session/);
  assert.equal(authorizationEvents, 1);
});

test('draft identities and saved markers are isolated by account and API endpoint', async (t) => {
  const state = setup(t);
  const first = state.session.prepare(state.params);
  const second = state.session.prepare({ ...state.params, userId: 'user-two' });
  const third = state.session.prepare({ ...state.params, apiBaseUrl: 'https://other.example.test' });
  assert.equal(new Set([first.clientRecordId, second.clientRecordId, third.clientRecordId]).size, 3);
  state.session.markSaved('https://other.example.test', first.userId, first.clientRecordId);
  state.session.markSaved(first.apiBaseUrl, 'other-user', first.clientRecordId);
  assert.equal((await state.session.deliver(first, state.io)).alreadySaved, false);
  assert.equal(state.posts.length, 1);
  assert.equal((await state.session.deliver(second, state.io)).alreadySaved, false);
  assert.equal((await state.session.deliver(third, state.io)).alreadySaved, false);
  assert.equal(state.posts[1].body.user_id, 'user-two');
  assert.equal(state.posts[2].url, 'https://other.example.test/record');
});

test('nonfinite food values are rejected before persistence or POST', async (t) => {
  const state = setup(t);
  const invalid = structuredClone(state.params);
  invalid.foods[0].nutrition.sodium = Infinity;
  assert.throws(() => state.session.prepare(invalid), /Invalid record number/);
  assert.equal(state.events.length, 0);
  assert.equal(state.posts.length, 0);
});

test('queue replay refuses a changed backend without POST or queue removal', async (t) => {
  const state = setup(t);
  const request = state.session.prepare(state.params);
  await state.io.persist(request);
  const [queued] = await state.queue.loadLegacy();
  assert.throws(() => assertPendingRecordSyncTarget(queued, 'https://other.example.test'), hasCode('target_mismatch'));
  assert.equal(state.posts.length, 0);
  assert.equal((await state.queue.loadAll()).length, 1);
});

test('Taiwan early-morning timestamp retains local date instead of the prior UTC day', () => {
  const helperUrl = new URL('../lib/record-submission.ts', import.meta.url).href;
  const datesUrl = new URL('../lib/dietary-records.ts', import.meta.url).href;
  const mealsUrl = new URL('../lib/meal.ts', import.meta.url).href;
  const script = `
    import { createRecordSubmissionSession } from ${JSON.stringify(helperUrl)};
    import { formatLocalTimestamp } from ${JSON.stringify(datesUrl)};
    import { getAutoMealType } from ${JSON.stringify(mealsUrl)};
    const session = createRecordSubmissionSession({ now: () => new Date('2026-11-14T00:03:00+08:00'),
      newId: () => 'morning', mealType: getAutoMealType, timestamp: formatLocalTimestamp });
    const request = session.prepare({ apiBaseUrl: 'https://example.test', userId: 'user',
      foods: [], source: 'camera', submissionKey: 'morning' });
    process.stdout.write(JSON.stringify({ timestamp: request.timestamp, mealType: request.mealType }));
  `;
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', script], {
    encoding: 'utf8', env: { ...process.env, TZ: 'Asia/Taipei' },
  });
  assert.equal(result.status, 0, result.stderr);
  const request = JSON.parse(result.stdout);
  assert.equal(request.timestamp, '2026-11-14T00:03:00.000+08:00');
  assert.equal(request.mealType, '\u65e9\u9910');
});
