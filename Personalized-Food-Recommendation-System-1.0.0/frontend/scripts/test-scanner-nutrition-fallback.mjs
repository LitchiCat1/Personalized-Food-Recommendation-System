import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const module = { exports: {} };
const code = ts.transpileModule(
  fs.readFileSync(new URL('../lib/scanner-nutrition-fallback.ts', import.meta.url), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } },
).outputText;
new Function('exports', code)(module.exports);
const { runScannerNutritionFallback } = module.exports;

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function fixture(overrides = {}) {
  let current = true;
  const events = [];
  return {
    events,
    invalidate: () => { current = false; },
    options: {
      mode: 'search',
      isCurrent: () => current,
      loadFdc: async () => { events.push('fdc'); return { status: 'empty' }; },
      onSnapshot: () => { events.push('snapshot'); },
      requestEnrichment: async () => { events.push('enrichment'); },
      ...overrides,
    },
  };
}

test('waits for raw FDC Search before publishing the snapshot or asking the server about enrichment', async () => {
  const db = fixture();
  const search = deferred();
  const run = runScannerNutritionFallback({
    ...db.options,
    loadFdc: () => { db.events.push('fdc'); return search.promise; },
  });
  assert.deepEqual(db.events, ['fdc']);
  search.resolve({ status: 'empty' });
  await run;
  assert.deepEqual(db.events, ['fdc', 'snapshot', 'enrichment']);
});

for (const [name, mode, response] of [
  ['reviewed zero', 'reviewed', { status: 'empty' }],
  ['reviewed hit', 'reviewed', { status: 'available', selection: {} }],
  ['raw candidates', 'search', { status: 'available' }],
  ['selection envelope in search mode', 'search', { status: 'empty', selection: {} }],
]) {
  test(`preserves FDC result without requesting enrichment: ${name}`, async () => {
    const db = fixture();
    await runScannerNutritionFallback({
      ...db.options, mode,
      loadFdc: async () => { db.events.push('fdc'); return response; },
    });
    assert.deepEqual(db.events, ['fdc', 'snapshot']);
  });
}

test('a failure does not trigger enrichment; a successful retry follows the same ordering', async () => {
  const db = fixture();
  await assert.rejects(runScannerNutritionFallback({
    ...db.options, loadFdc: async () => { throw new Error('FDC unavailable'); },
  }), /FDC unavailable/);
  assert.deepEqual(db.events, []);
  await runScannerNutritionFallback(db.options);
  assert.deepEqual(db.events, ['fdc', 'snapshot', 'enrichment']);
});

test('without an enrichment capability raw FDC still works', async () => {
  const db = fixture({ requestEnrichment: undefined });
  await runScannerNutritionFallback(db.options);
  assert.deepEqual(db.events, ['fdc', 'snapshot']);
});

test('does not load an already stale reference or apply an in-flight stale response', async () => {
  const old = fixture();
  old.invalidate();
  await runScannerNutritionFallback(old.options);
  assert.deepEqual(old.events, []);

  const current = fixture();
  const search = deferred();
  const run = runScannerNutritionFallback({ ...current.options, loadFdc: () => search.promise });
  current.invalidate();
  search.resolve({ status: 'empty' });
  await run;
  assert.deepEqual(current.events, []);
});
