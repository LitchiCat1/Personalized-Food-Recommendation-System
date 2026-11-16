import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const filename = fileURLToPath(new URL('../lib/nutrition-enrichment-api.ts', import.meta.url));
const module = { exports: {} };
const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
new Function('require', 'module', 'exports', code)((id) => {
  if (id === './api') return {};
  throw new Error(`Unexpected runtime dependency: ${id}`);
}, module, module.exports);
const api = module.exports;

const ITEM = {
  item_id: 'scan-1:0', item_revision: 0, name_zh: '糯米腸', confidence: 0.92,
  weight_confidence: 0.8, estimated_weight_g: 120, food_state: 'prepared',
  preparation_method: 'roasted', components_scope: 'food_only', brand: null, variant: null,
  validation_issues: [],
};
const REQUEST = {
  user_id: 'u1', scan_id: 'scan-1', scan_revision: 0, items: [ITEM],
  idempotency_key: 'scan-1:enrichment', source_policy_id: 'web-policy', source_policy_revision: 0,
};

test('builds an enrichment request from server-owned scan context', () => {
  const request = api.buildNutritionEnrichmentRequest({
    userId: 'u1',
    context: {
      status: 'persisted', scan_id: 'scan-2', scan_revision: 3,
      authority_token: 'scan-authority', items: [ITEM],
    },
    sourcePolicyId: 'policy-1', sourcePolicyRevision: 4,
  });
  assert.deepEqual(request, {
    user_id: 'u1', scan_id: 'scan-2', scan_revision: 3, items: [ITEM],
    idempotency_key: 'nutrition:scan-2:3', source_policy_id: 'policy-1',
    source_policy_revision: 4, scan_authority_token: 'scan-authority',
  });
});

async function withFetch(handler, run) {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async (...args) => { calls += 1; return handler(...args); };
  try { return await run(() => calls); } finally { globalThis.fetch = original; }
}

test('feature gate rejects before network and preserves legacy safety', async () => {
  await withFetch(() => { throw new Error('must not fetch'); }, async (calls) => {
    await assert.rejects(api.requestNutritionEnrichment('https://example.test', REQUEST),
      (error) => error.code === 'feature_disabled' && error.status === 503);
    assert.equal(calls(), 0);
  });
});

test('invalid client request is rejected before network', async () => {
  await withFetch(() => { throw new Error('must not fetch'); }, async (calls) => {
    await assert.rejects(api.requestNutritionEnrichment('https://example.test', { ...REQUEST, items: [] }, undefined, { enabled: true }),
      (error) => error.code === 'invalid_request');
    assert.equal(calls(), 0);
  });
});

test('success response validates envelope and preserves coverage without legacy coercion', async () => {
  const body = {
    status: 'partial', request_id: 'req-1', replayed: false,
    result: { schema_version: 'NutritionEnrichmentRouteV1', items: [{ item_id: ITEM.item_id, status: 'needs_portion' }],
      nutrition_coverage: { status: 'incomplete', unresolved_item_ids: [ITEM.item_id] } },
    error: null,
  };
  let requestBody;
  await withFetch((url, init) => {
    assert.equal(url, 'https://example.test/nutrition/enrichment');
    assert.equal(init.method, 'POST');
    assert.equal(init.headers.Authorization, 'Bearer token');
    requestBody = JSON.parse(init.body);
    return new Response(JSON.stringify(body), { status: 200 });
  }, async (calls) => {
    const response = await api.requestNutritionEnrichment('https://example.test/', REQUEST, { accessToken: 'token' }, { enabled: true });
    assert.equal(response.status, 'partial');
    assert.equal(response.result.nutrition_coverage.status, 'incomplete');
    assert.deepEqual(requestBody, REQUEST);
    assert.equal(calls(), 1);
  });
});

test('scan authority and profile references pass through unchanged', async () => {
  const request = {
    ...REQUEST,
    wait_timeout: 7.5,
    scan_authority_token: 'scan-token.v1',
    profiles: [{
      profile_id: 'profile-1',
      profile_hash: 'a'.repeat(64),
      source_id: 'source-1',
      profile_revision: 3,
    }],
  };
  const body = {
    status: 'complete', request_id: 'req-authority', replayed: false,
    result: { schema_version: 'NutritionEnrichmentRouteV1', items: [], nutrition_coverage: {} },
    error: null,
  };
  let requestBody;
  await withFetch((_url, init) => {
    requestBody = JSON.parse(init.body);
    return new Response(JSON.stringify(body), { status: 200 });
  }, async () => {
    const response = await api.requestNutritionEnrichment(
      'https://example.test', request, undefined, { enabled: true });
    assert.equal(response.status, 'complete');
    assert.deepEqual(requestBody, request);
  });
});

test('accepted 202 pending response is preserved as pending', async () => {
  const body = {
    status: 'pending', request_id: 'req-pending', replayed: false,
    result: null, error: null,
  };
  await withFetch(() => new Response(JSON.stringify(body), { status: 202 }), async () => {
    const response = await api.requestNutritionEnrichment(
      'https://example.test', REQUEST, undefined, { enabled: true });
    assert.equal(response.status, 'pending');
    assert.equal(response.request_id, 'req-pending');
    assert.equal(response.result, null);
    assert.equal(response.error, null);
  });
});

test('confirmation and retry errors retain typed backend code and Retry-After', async () => {
  await withFetch(() => new Response(JSON.stringify({ error: { code: 'confirmation_required', message: 'confirm food identity' } }), {
    status: 409, headers: { 'Retry-After': '60' },
  }), async () => {
    await assert.rejects(api.requestNutritionEnrichment('https://example.test', REQUEST, undefined, { enabled: true }),
      (error) => error.code === 'confirmation_required' && error.status === 409 && error.retryAfter === '60');
  });
});

test('malformed success response is rejected instead of cast into a result', async () => {
  await withFetch(() => new Response(JSON.stringify({ status: 'complete', request_id: null, replayed: false, result: {} }), {
    status: 200,
  }), async () => {
    await assert.rejects(api.requestNutritionEnrichment('https://example.test', REQUEST, undefined, { enabled: true }),
      (error) => error.code === 'invalid_response');
  });
});

