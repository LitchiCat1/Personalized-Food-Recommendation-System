import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ts = require('typescript');
let unauthorizedCalls = 0;
const filename = fileURLToPath(new URL('../lib/nutrition-fdc-confirmation-api.ts', import.meta.url));
const module = { exports: {} };
const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
new Function('require', 'module', 'exports', code)((id) => {
  if (id === './auth') return { reportUnauthorized() { unauthorizedCalls += 1; } };
  if (id === './nutrition-fdc-candidate-api') return {};
  throw new Error(`Unexpected runtime dependency: ${id}`);
}, module, module.exports);
const api = module.exports;

const snapshot = {
  status: 'available',
  snapshot: {
    scan_id: 'scan-1', scan_revision: 3, snapshot_digest: 'a'.repeat(64), expires_at: Date.now() / 1000 + 300,
    snapshot: {
      schema_version: 'FdcCandidateSnapshotV1', scan_revision: 3,
      item_set_digest: 'b'.repeat(64), snapshot_digest: 'a'.repeat(64),
      items: [{
        item_id: 'scan-1:0', item_revision: 0, identity_digest: 'c'.repeat(64),
        recognition_identity: {
          name_zh: '糯米腸', food_state: 'prepared', preparation_method: 'steamed',
          components_scope: 'food_only', brand: null, variant: null,
        },
        candidates: [{
          fdcId: '123456', description: 'Rice sausage, cooked', dataType: 'Foundation',
          brandOwner: null, foodCategory: 'Prepared foods',
        }],
      }],
    },
  },
};

const request = api.buildNutritionFdcConfirmationRequest({
  snapshot, idempotencyKey: 'fdc-confirmation:scan-1:3',
  decisions: [{ item_id: 'scan-1:0', decision: 'confirm', candidate_fdc_id: '123456' }],
});

function response() {
  return {
    status: 'confirmed_pending_revision', confirmation_id: 'confirmation-1', scan_id: 'scan-1', scan_revision: 3,
    issued_scan_revision: 4, requires_detail_replay: true, snapshot_digest: 'a'.repeat(64),
    items: [{
      item_id: 'scan-1:0', status: 'confirmed_pending_revision', item_revision: 0,
      confirmed_fdc_id: '123456', snapshot_digest: 'a'.repeat(64), scan_revision: 3,
      identity_digest: 'c'.repeat(64), requires_new_scan_revision: true, requires_user_confirmation: false,
    }],
    requires_new_scan_revision: true, photo_confidence_changed: false, replayed: false,
  };
}

async function withFetch(handler, run) {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async (...args) => { calls += 1; return handler(...args); };
  try { return await run(() => calls); } finally { globalThis.fetch = original; }
}

test('confirmation stays disabled before network access', async () => {
  await withFetch(() => { throw new Error('must not fetch'); }, async (calls) => {
    await assert.rejects(api.confirmNutritionFdcCandidates('https://example.test', request, snapshot),
      (error) => error.code === 'feature_disabled' && error.status === 503);
    assert.equal(calls(), 0);
  });
});

test('request contains only scan reference, idempotency key and digest-bound user decisions', async () => {
  await withFetch((url, init) => {
    assert.equal(url, 'https://example.test/nutrition/fdc/confirmation');
    assert.equal(init.method, 'POST');
    assert.equal(init.headers.Authorization, 'Bearer test-token');
    assert.deepEqual(JSON.parse(init.body), request);
    return new Response(JSON.stringify(response()), { status: 202 });
  }, async () => {
    const result = await api.confirmNutritionFdcCandidates('https://example.test/', request, snapshot,
      { accessToken: 'test-token' }, { enabled: true });
    assert.equal(result.issued_scan_revision, 4);
    assert.equal(result.photo_confidence_changed, false);
  });
});

test('builder rejects IDs not present in the snapshot and incomplete decisions', () => {
  assert.throws(() => api.buildNutritionFdcConfirmationRequest({
    snapshot, idempotencyKey: 'key',
    decisions: [{ item_id: 'scan-1:0', decision: 'confirm', candidate_fdc_id: '999999' }],
  }), (error) => error.code === 'invalid_request');
  assert.throws(() => api.buildNutritionFdcConfirmationRequest({
    snapshot, idempotencyKey: 'key', decisions: [],
  }), (error) => error.code === 'invalid_request');
});

test('defer and reject decisions cannot carry a candidate ID', () => {
  for (const decision of ['defer', 'reject']) {
    assert.throws(() => api.buildNutritionFdcConfirmationRequest({
      snapshot, idempotencyKey: 'key',
      decisions: [{ item_id: 'scan-1:0', decision, candidate_fdc_id: '123456' }],
    }), (error) => error.code === 'invalid_request');
  }
});

test('transport rejects injected fields instead of posting client-owned nutrition or weight', async () => {
  const injected = { ...request, weight_g: 500, profile: { calories: 200 } };
  await withFetch(() => { throw new Error('must not fetch'); }, async (calls) => {
    await assert.rejects(api.confirmNutritionFdcCandidates('https://example.test', injected, snapshot,
      undefined, { enabled: true }), (error) => error.code === 'invalid_request');
    assert.equal(calls(), 0);
  });
});

test('response rejects nutrition, identity drift, confidence mutation and revision mismatch', async () => {
  const mutations = [
    (value) => { value.nutrition = { calories: 200 }; },
    (value) => { value.photo_confidence_changed = true; },
    (value) => { value.items[0].identity_digest = 'd'.repeat(64); },
    (value) => { value.issued_scan_revision = 5; },
    (value) => { value.items[0].nutrition_profile = {}; },
  ];
  for (const mutate of mutations) {
    const value = response();
    mutate(value);
    await withFetch(() => new Response(JSON.stringify(value), { status: 202 }), async () => {
      await assert.rejects(api.confirmNutritionFdcCandidates('https://example.test', request, snapshot,
        undefined, { enabled: true }), (error) => error.code === 'invalid_response');
    });
  }
});

test('stale session 401 does not notify the active account', async () => {
  const before = unauthorizedCalls;
  await withFetch(() => new Response(JSON.stringify({ error: { code: 'unauthorized', message: 'expired' } }), {
    status: 401,
  }), async () => {
    await assert.rejects(api.confirmNutritionFdcCandidates('https://example.test', request, snapshot,
      { accessToken: 'old-token' }, { enabled: true, isCurrentSession: () => false }),
    (error) => error.status === 401);
  });
  assert.equal(unauthorizedCalls, before);
});
