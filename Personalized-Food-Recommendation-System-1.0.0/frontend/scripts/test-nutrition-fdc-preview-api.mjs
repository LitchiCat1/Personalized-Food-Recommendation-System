import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const filename = fileURLToPath(new URL('../lib/nutrition-fdc-preview-api.ts', import.meta.url));
const module = { exports: {} };
let unauthorizedReports = 0;
const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
new Function('require', 'module', 'exports', code)((id) => {
  if (id === './auth') return { reportUnauthorized() { unauthorizedReports += 1; } };
  throw new Error(`Unexpected runtime dependency: ${id}`);
}, module, module.exports);
const api = module.exports;

const REQUEST = {
  confirmation_id: 'confirmation-1', scan_id: 'scan-1', issued_scan_revision: 1,
  item_id: 'scan-1:0',
};
const ACCEPT = { preview_id: 'preview-1', idempotency_key: 'accept-1' };

async function withFetch(handler, run) {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async (...args) => { calls += 1; return handler(...args); };
  try { return await run(() => calls); } finally { globalThis.fetch = original; }
}

test('preview and accept feature gates reject before network by default', async () => {
  await withFetch(() => { throw new Error('must not fetch'); }, async (calls) => {
    await assert.rejects(api.requestNutritionFdcProfilePreview('https://example.test', REQUEST),
      (error) => error.code === 'feature_disabled' && error.status === 503);
    await assert.rejects(api.requestNutritionFdcProfileAccept('https://example.test', ACCEPT),
      (error) => error.code === 'feature_disabled' && error.status === 503);
    assert.equal(calls(), 0);
  });
});

test('disabled feature gate wins over malformed request validation', async () => {
  await withFetch(() => { throw new Error('must not fetch'); }, async (calls) => {
    await assert.rejects(api.requestNutritionFdcProfilePreview('https://example.test', {
      confirmation_id: '', scan_id: '', issued_scan_revision: -1, item_id: '',
    }), (error) => error.code === 'feature_disabled' && error.status === 503);
    await assert.rejects(api.requestNutritionFdcProfileAccept('https://example.test', {
      preview_id: '', idempotency_key: '',
    }), (error) => error.code === 'feature_disabled' && error.status === 503);
    assert.equal(calls(), 0);
  });
});

test('preview request rejects injected provider fields before network', async () => {
  await withFetch(() => { throw new Error('must not fetch'); }, async (calls) => {
    await assert.rejects(api.requestNutritionFdcProfilePreview('https://example.test', {
      ...REQUEST, fdc_id: '99999', profile: { calories: 1 }, weight_g: 1,
    }, undefined, { enabled: true }), (error) => error.code === 'invalid_request');
    assert.equal(calls(), 0);
  });
});

const PREVIEW_RESPONSE = {
  status: 'preview_ready', preview_id: 'preview-1', confirmation_id: REQUEST.confirmation_id,
  scan_id: REQUEST.scan_id, issued_scan_revision: 1, item_id: REQUEST.item_id,
  item_revision: 0, snapshot_digest: 'a'.repeat(64), source_id: 'usda-fdc-171688',
  source_policy_revision: 2, fdc_id: '171688', weight_g: 150,
  preview: {
    nutrition_profile: { schema_version: 'NutritionProfileV1' }, portion: { weight_g: 150 },
    source_block: { content_hash: 'b'.repeat(64) }, recognition_identity: { name_zh: '蘋果' },
    source_identity: { name_zh: '蘋果' },
  }, photo_confidence_changed: false, profile_written: false,
};

test('preview and accept send only references and validate responses', async () => {
  const calls = [];
  await withFetch((url, init) => {
    calls.push({ url, init });
    const body = JSON.parse(init.body);
    if (url.endsWith('/profile-preview')) {
      assert.deepEqual(body, REQUEST);
      assert.equal(init.headers.Authorization, 'Bearer token');
      return new Response(JSON.stringify(PREVIEW_RESPONSE), { status: 200 });
    }
    assert.deepEqual(body, ACCEPT);
    assert.equal(init.headers.Authorization, 'Bearer token');
    return new Response(JSON.stringify({
      status: 'accepted', preview_id: 'preview-1', profile: { profile_id: 'p1' },
      portion: { weight_g: 150 }, profile_hash: 'c'.repeat(64), replayed: false,
      photo_confidence_changed: false, profile_written: true,
    }), { status: 200 });
  }, async () => {
    const preview = await api.requestNutritionFdcProfilePreview('https://example.test/', REQUEST,
      { accessToken: 'token' }, { enabled: true });
    assert.equal(preview.fdc_id, '171688');
    const accepted = await api.requestNutritionFdcProfileAccept('https://example.test/', ACCEPT,
      { accessToken: 'token' }, { enabled: true });
    assert.equal(accepted.status, 'accepted');
    assert.equal(calls.length, 2);
  });
});

test('backend error code and Retry-After are preserved', async () => {
  await withFetch(() => new Response(JSON.stringify({ error: { code: 'expired', message: 'expired' } }), {
    status: 409, headers: { 'Retry-After': '30' },
  }), async () => {
    await assert.rejects(api.requestNutritionFdcProfileAccept('https://example.test', ACCEPT,
      undefined, { enabled: true }),
    (error) => error.code === 'expired' && error.status === 409 && error.retryAfter === '30');
  });
});

test('malformed success response is rejected instead of cast', async () => {
  await withFetch(() => new Response(JSON.stringify({ ...PREVIEW_RESPONSE, fdc_id: null }), {
    status: 200,
  }), async () => {
    await assert.rejects(api.requestNutritionFdcProfilePreview('https://example.test', REQUEST,
      undefined, { enabled: true }), (error) => error.code === 'invalid_response');
  });
});

test('preview response must stay bound to its confirmation, scan revision and item', async () => {
  for (const change of [
    { confirmation_id: 'other-confirmation' },
    { scan_id: 'other-scan' },
    { issued_scan_revision: 2 },
    { item_id: 'other-item' },
  ]) {
    await withFetch(() => new Response(JSON.stringify({ ...PREVIEW_RESPONSE, ...change }), { status: 200 }), async () => {
      await assert.rejects(api.requestNutritionFdcProfilePreview('https://example.test', REQUEST,
        undefined, { enabled: true }), (error) => error.code === 'invalid_response');
    });
  }
});

test('preview ignores a stale session 401 after the active account changes', async () => {
  const reportsBeforeRequest = unauthorizedReports;
  await withFetch(() => new Response(JSON.stringify({ error: { code: 'unauthorized' } }), { status: 401 }), async () => {
    await assert.rejects(api.requestNutritionFdcProfilePreview('https://example.test', REQUEST,
      undefined, { enabled: true, isCurrentSession: () => false }),
    (error) => error.status === 401 && error.code === 'unauthorized');
  });
  assert.equal(unauthorizedReports, reportsBeforeRequest);
});

test('preview response rejects uncontracted confidence fields', async () => {
  await withFetch(() => new Response(JSON.stringify({ ...PREVIEW_RESPONSE, confidence: 0.99 }), { status: 200 }), async () => {
    await assert.rejects(api.requestNutritionFdcProfilePreview('https://example.test', REQUEST,
      undefined, { enabled: true }), (error) => error.code === 'invalid_response');
  });
  await withFetch(() => new Response(JSON.stringify({
    ...PREVIEW_RESPONSE, preview: { ...PREVIEW_RESPONSE.preview, confidence: 0.99 },
  }), { status: 200 }), async () => {
    await assert.rejects(api.requestNutritionFdcProfilePreview('https://example.test', REQUEST,
      undefined, { enabled: true }), (error) => error.code === 'invalid_response');
  });
});

