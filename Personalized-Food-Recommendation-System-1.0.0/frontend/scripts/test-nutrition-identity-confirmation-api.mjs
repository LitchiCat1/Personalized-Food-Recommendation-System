import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const filename = fileURLToPath(new URL('../lib/nutrition-identity-confirmation-api.ts', import.meta.url));
const module = { exports: {} };
const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
new Function('require', 'module', 'exports', code)((id) => {
  if (id === './api') return {};
  throw new Error(`Unexpected runtime dependency: ${id}`);
}, module, module.exports);
const api = module.exports;

const CONTEXT = {
  status: 'persisted', scan_id: 'scan-1', scan_revision: 2,
  items: [{
    item_id: 'scan-1:0', item_revision: 3, name_zh: '炒菜葉',
    food_state: 'prepared', preparation_method: 'stir_fried', components_scope: 'food_only',
    validation_issues: [], identity_confirmation_required: true,
  }],
};

const RESPONSE = {
  status: 'confirmed', decision: 'correct', confirmation_id: 'server-confirmation',
  scan_id: 'scan-1', source_scan_revision: 2, issued_scan_revision: 3,
  item_id: 'scan-1:0', source_item_revision: 3, issued_item_revision: 4,
  name_zh: '青江菜', identity_confirmation_required: false,
  identity_confirmation_source: 'user', identity_confirmation_id: 'server-confirmation',
  expires_at: 2000, replayed: false, local_lookup: { status: 'no_local_mapping', item: null },
};

test('builds exact scan-bound name decision without client confirmation flags', () => {
  const request = api.buildNutritionIdentityConfirmationRequest({
    context: CONTEXT, itemId: 'scan-1:0', name: '青江菜', idempotencyKey: 'identity-1',
  });
  assert.deepEqual(Object.keys(request).sort(), [
    'idempotency_key', 'item_id', 'item_revision', 'name_zh', 'scan_id', 'scan_revision',
  ]);
  assert.equal(request.scan_revision, 2);
  assert.equal(request.item_revision, 3);
  assert.equal('confirmed' in request, false);
});

test('requires an unresolved, valid server item context before building', () => {
  assert.throws(() => api.buildNutritionIdentityConfirmationRequest({
    context: CONTEXT, itemId: 'other-item', name: '青江菜', idempotencyKey: 'identity-2',
  }), { code: 'invalid_request' });
  assert.throws(() => api.buildNutritionIdentityConfirmationRequest({
    context: { ...CONTEXT, items: [{ ...CONTEXT.items[0], validation_issues: ['bad_state'] }] },
    itemId: 'scan-1:0', name: '青江菜', idempotencyKey: 'identity-3',
  }), { code: 'invalid_request' });
});

test('feature gate and strict response revision binding are enforced', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: true, status: 202, headers: new Headers(), json: async () => RESPONSE,
  });
  try {
    const request = api.buildNutritionIdentityConfirmationRequest({
      context: CONTEXT, itemId: 'scan-1:0', name: '青江菜', idempotencyKey: 'identity-4',
    });
    await assert.rejects(api.confirmNutritionIdentity('http://localhost:5000', request),
      { code: 'feature_disabled' });
    const result = await api.confirmNutritionIdentity('http://localhost:5000', request, undefined,
      { enabled: true });
    assert.equal(result.issued_scan_revision, 3);
    globalThis.fetch = async () => ({
      ok: true, status: 202, headers: new Headers(),
      json: async () => ({ ...RESPONSE, issued_scan_revision: 4 }),
    });
    await assert.rejects(api.confirmNutritionIdentity('http://localhost:5000', request, undefined,
      { enabled: true }), { code: 'invalid_response' });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('a stale-session 401 does not emit an unauthorized event', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const events = [];
  globalThis.window = { dispatchEvent: (event) => events.push(event.type) };
  globalThis.fetch = async () => ({
    ok: false, status: 401, headers: new Headers(), json: async () => ({ error: { code: 'unauthorized', message: 'expired' } }),
  });
  try {
    const request = api.buildNutritionIdentityConfirmationRequest({
      context: CONTEXT, itemId: 'scan-1:0', name: '青江菜', idempotencyKey: 'identity-5',
    });
    await assert.rejects(api.confirmNutritionIdentity('http://localhost:5000', request, undefined,
      { enabled: true, isCurrentSession: () => false }));
    assert.deepEqual(events, []);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});
