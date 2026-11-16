import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ts = require('typescript');
let unauthorizedCalls = 0;
const filename = fileURLToPath(new URL('../lib/nutrition-fdc-candidate-api.ts', import.meta.url));
const module = { exports: {} };
const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
new Function('require', 'module', 'exports', code)((id) => {
  if (id === './auth') return { reportUnauthorized() { unauthorizedCalls += 1; } };
  throw new Error(`Unexpected runtime dependency: ${id}`);
}, module, module.exports);
const api = module.exports;

const REQUEST = { scan_id: 'scan-1', scan_revision: 3 };
const IDENTITY = {
  name_zh: '糯米腸', food_state: 'prepared', preparation_method: 'steamed',
  components_scope: 'food_only', brand: null, variant: null,
};

function response(status = 'available') {
  const candidates = status === 'available' ? [{
    fdcId: '123456', description: 'Rice sausage, cooked', dataType: 'Foundation',
    brandOwner: null, foodCategory: 'Prepared foods',
  }] : [];
  const snapshotDigest = 'a'.repeat(64);
  return {
    status,
    snapshot: {
      scan_id: REQUEST.scan_id,
      scan_revision: REQUEST.scan_revision,
      snapshot_digest: snapshotDigest,
      expires_at: Math.floor(Date.now() / 1000) + 300,
      snapshot: {
        schema_version: 'FdcCandidateSnapshotV1',
        scan_revision: REQUEST.scan_revision,
        item_set_digest: 'b'.repeat(64),
        snapshot_digest: snapshotDigest,
        items: [{
          item_id: 'scan-1:0', item_revision: 0, identity_digest: 'c'.repeat(64),
          recognition_identity: IDENTITY, candidates,
        }],
      },
    },
  };
}

async function withFetch(handler, run) {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async (...args) => { calls += 1; return handler(...args); };
  try { return await run(() => calls); } finally { globalThis.fetch = original; }
}

test('candidate search and read stay disabled before any network request', async () => {
  await withFetch(() => { throw new Error('must not fetch'); }, async (calls) => {
    await assert.rejects(api.createNutritionFdcCandidateSnapshot('https://example.test', REQUEST),
      (error) => error.code === 'feature_disabled' && error.status === 503);
    await assert.rejects(api.getNutritionFdcCandidateSnapshot('https://example.test', REQUEST),
      (error) => error.code === 'feature_disabled' && error.status === 503);
    assert.equal(calls(), 0);
  });
});

test('only scan references are sent to the authenticated create/read endpoints', async () => {
  const calls = [];
  await withFetch((url, init) => {
    calls.push({ url, init });
    if (init.method === 'POST') {
      assert.deepEqual(JSON.parse(init.body), REQUEST);
      assert.equal(init.headers.Authorization, 'Bearer test-token');
    } else {
      assert.equal(url, 'https://example.test/nutrition/fdc/candidates?scan_id=scan-1&scan_revision=3');
      assert.equal('body' in init, false);
      assert.equal(init.headers.Authorization, 'Bearer test-token');
    }
    return new Response(JSON.stringify(response()), { status: 200 });
  }, async () => {
    const created = await api.createNutritionFdcCandidateSnapshot('https://example.test/', REQUEST,
      { accessToken: 'test-token' }, { enabled: true });
    const loaded = await api.getNutritionFdcCandidateSnapshot('https://example.test/', REQUEST,
      { accessToken: 'test-token' }, { enabled: true });
    assert.equal(created.status, 'available');
    assert.equal(created.snapshot.snapshot.items[0].candidates[0].fdcId, '123456');
    assert.deepEqual(loaded, created);
    assert.equal(calls.length, 2);
  });
});

test('empty candidate snapshots are valid and distinct from API failures', async () => {
  await withFetch(() => new Response(JSON.stringify(response('empty')), { status: 200 }), async () => {
    const result = await api.createNutritionFdcCandidateSnapshot('https://example.test', REQUEST,
      undefined, { enabled: true });
    assert.equal(result.status, 'empty');
    assert.deepEqual(result.snapshot.snapshot.items[0].candidates, []);
  });
});

test('malformed, cross-scan, or nutrition-bearing responses are rejected', async () => {
  const malformed = [
    { ...response(), snapshot: { ...response().snapshot, scan_id: 'another-scan' } },
    { ...response(), debug: 'unexpected root field' },
    (() => {
      const value = response();
      value.snapshot.snapshot.items[0].nutrition = { calories: 100 };
      return value;
    })(),
    (() => {
      const value = response();
      value.snapshot.snapshot.items[0].candidates[0].fdcId = '0123';
      return value;
    })(),
    (() => {
      const value = response();
      value.snapshot.expires_at = -1;
      return value;
    })(),
    (() => {
      const value = response();
      value.status = 'empty';
      return value;
    })(),
  ];
  for (const value of malformed) {
    await withFetch(() => new Response(JSON.stringify(value), { status: 200 }), async () => {
      await assert.rejects(api.createNutritionFdcCandidateSnapshot('https://example.test', REQUEST,
        undefined, { enabled: true }), (error) => error.code === 'invalid_response');
    });
  }
});

test('request builder rejects client-owned snapshot and candidate fields', () => {
  assert.deepEqual(api.buildNutritionFdcCandidateRequest(REQUEST), REQUEST);
  assert.throws(() => api.buildNutritionFdcCandidateRequest({
    ...REQUEST, snapshot_digest: 'a'.repeat(64),
  }), (error) => error.code === 'invalid_request');
});

test('device clock skew does not override server-owned candidate expiry', async () => {
  const value = response();
  value.snapshot.expires_at = Math.floor(Date.now() / 1000) - 60;
  await withFetch(() => new Response(JSON.stringify(value), { status: 200 }), async () => {
    const result = await api.createNutritionFdcCandidateSnapshot('https://example.test', REQUEST,
      undefined, { enabled: true });
    assert.equal(result.snapshot.expires_at, value.snapshot.expires_at);
  });
});

test('backend error code and Retry-After are retained', async () => {
  await withFetch(() => new Response(JSON.stringify({ error: { code: 'rate_limited', message: 'slow down' } }), {
    status: 429, headers: { 'Retry-After': '60' },
  }), async () => {
    await assert.rejects(api.createNutritionFdcCandidateSnapshot('https://example.test', REQUEST,
      undefined, { enabled: true }),
    (error) => error.code === 'rate_limited' && error.status === 429 && error.retryAfter === '60');
  });
});

test('stale session 401 does not notify the currently signed-in account', async () => {
  const before = unauthorizedCalls;
  await withFetch(() => new Response(JSON.stringify({ error: { code: 'unauthorized', message: 'expired' } }), {
    status: 401,
  }), async () => {
    await assert.rejects(api.createNutritionFdcCandidateSnapshot('https://example.test', REQUEST,
      { accessToken: 'old-token' }, { enabled: true, isCurrentSession: () => false }),
    (error) => error.status === 401);
  });
  assert.equal(unauthorizedCalls, before);
});
