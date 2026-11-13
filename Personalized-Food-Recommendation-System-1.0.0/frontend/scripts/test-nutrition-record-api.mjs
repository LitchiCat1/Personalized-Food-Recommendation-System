import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
import * as calculation from '../lib/nutrition-calculation.ts';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const apiFile = fileURLToPath(new URL('../lib/nutrition-record-api.ts', import.meta.url));
const module = { exports: {} };
const code = ts.transpileModule(fs.readFileSync(apiFile, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
new Function('require', 'module', 'exports', code)((id) => {
  if (id === './nutrition-calculation') return calculation;
  throw new Error(`Unexpected runtime dependency: ${id}`);
}, module, module.exports);
const api = module.exports;

// Build real server snapshots without app initialization, network, or a database.
const backend = path.resolve(path.dirname(apiFile), '../../backend');
const fixture = spawnSync('python', ['-c', `
import json, socket, sys
sys.path.insert(0, sys.argv[1])
socket.socket = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('network disabled'))
from services.record_nutrition_service import normalize_v2_record, aggregate_record_coverage
from services.history_service import build_history_response
keys = ('calories','protein','carbs','sugar','fat','saturated_fat','trans_fat','sodium','fiber')
nutrients = dict.fromkeys(keys, None)
nutrients.update(calories=100, protein=4, carbs=10, fat=5, sodium=0,
                 sugar={'value':'0.1','unit':'g','comparison':'less_than'})
payload = {'nutrition_contract_version':2,'user_id':'user/a','client_record_id':'meal/a',
           'timestamp':'2026-11-13T23:50:00+08:00','meal_type':'晚餐','source':'camera',
           'foods':[{'item_id':'a','name':'rice','weight_g':150,'portion_source':'user_weighed',
                     'user_entered_nutrients':nutrients},
                    {'item_id':'b','name':'sauce','weight_g':None,'portion_source':'unknown'}],
           'nutrition_context':{'scan_id':'scan-a','recognition_context':{'items':[{'item_id':'a'},{'item_id':'b'}]}}}
canonical = normalize_v2_record(payload)
record = dict(canonical, user_id='user/a', client_record_id='meal/a', timestamp=payload['timestamp'], meal_type='晚餐')
legacy = {'user_id':'user/a','client_record_id':'old','timestamp':payload['timestamp'],
          'foods':[{'name':'legacy','calories':0}], 'total_calories':0}
class Storage:
    def get_history(self, *args, **kwargs):
        coverage = aggregate_record_coverage([record,legacy])
        return [dict({'date':'2026-11-13','record_count':2,'nutrition_coverage':coverage},
                     **{k:coverage['nutrients'][k]['known_sum'] for k in keys})]
print(json.dumps({'payload':payload,'canonical':canonical,'record':record,'legacy':legacy,
                  'history':build_history_response(Storage(),'user/a',7,nutrition_contract_version=2)}))
`, backend], { encoding: 'utf8', env: { ...process.env, NUTRILENS_SKIP_LOCAL_ENV: '1', PYTHONIOENCODING: 'utf-8' } });
assert.equal(fixture.status, 0, fixture.stderr);
const data = JSON.parse(fixture.stdout);

async function withResponse(body, run, status = 200) {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, ...init });
    return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status });
  };
  try { return await run(calls); } finally { globalThis.fetch = original; }
}

test('preview accepts actual backend nullable snapshot and preserves unresolved IDs and bounds', async () => {
  await withResponse({ record: data.canonical }, async (calls) => {
    const result = await api.previewNutritionRecordV2('https://example.test/', data.payload, { accessToken: 'test-only' });
    assert.deepEqual(result.record, data.canonical);
    assert.equal(result.record.foods[0].sodium, 0);
    assert.equal(result.record.foods[0].sugar, null);
    assert.equal(result.record.foods[0].nutrition_intake.upper_bounds.sugar, 0.15);
    assert.equal(result.record.foods[1].weight_g, null);
    assert.equal(result.record.nutrition_context.coverage.nutrients.calories.eligible_items, 2);
    assert.equal(calls[0].url, 'https://example.test/record/preview');
    assert.equal(calls[0].headers['X-Nutrition-Contract-Version'], '2');
    assert.equal(calls[0].headers.Authorization, 'Bearer test-only');
    assert.deepEqual(JSON.parse(calls[0].body), data.payload);
  });
});

test('create sends original payload and never substitutes response snapshot or new date', async () => {
  await withResponse({ record: data.record, deduplicated: false, message: 'saved' }, async (calls) => {
    const result = await api.createNutritionRecordV2('https://example.test', data.payload);
    assert.equal(result.record.nutrition_contract_version, 2);
    assert.equal(JSON.parse(calls[0].body).timestamp, '2026-11-13T23:50:00+08:00');
    assert.ok(!('nutrition_profile' in JSON.parse(calls[0].body).foods[0]));
  }, 201);
});

test('duplicate POST can explicitly return legacy record without relabeling or converting zeros', async () => {
  await withResponse({ record: data.legacy, deduplicated: true, message: 'exists' }, async () => {
    const result = await api.createNutritionRecordV2('https://example.test', data.payload);
    assert.equal(result.record.nutrition_contract_version, undefined);
    assert.equal(result.record.total_calories, 0);
  });
});

test('edit sends revision and minimal identities without source snapshot', async () => {
  const patch = { nutrition_contract_version: 2, base_revision: 3, foods: data.payload.foods };
  await withResponse({ record: data.record, message: 'updated' }, async (calls) => {
    await api.updateNutritionRecordV2('https://example.test', 'user/a', 'meal/a', patch);
    assert.equal(calls[0].method, 'PATCH');
    assert.equal(calls[0].url, 'https://example.test/records/user%2Fa/meal%2Fa');
    assert.deepEqual(JSON.parse(calls[0].body), patch);
  });
});

test('mixed version page preserves version boundary and pagination scope', async () => {
  await withResponse({ records: [data.legacy, data.record], count: 2 }, async (calls) => {
    const result = await api.fetchNutritionRecordsV2('https://example.test', 'user/a', '2026-11-13', undefined, { limit: 2, offset: 4 });
    assert.equal(result.records[0].nutrition_contract_version, undefined);
    assert.equal(result.records[1].nutrition_contract_version, 2);
    assert.equal(calls[0].url, 'https://example.test/records/user%2Fa?date=2026-11-13&limit=2&offset=4');
    assert.equal(result.nutrition_coverage, undefined);
  });
});

test('history retains actual server legacy_unknown and known-sum scope', async () => {
  await withResponse(data.history, async () => {
    const result = await api.fetchNutritionHistoryV2('https://example.test', 'user/a');
    assert.equal(result.summary.nutrition_coverage.nutrients.calories.status, 'legacy_unknown');
    assert.equal(result.summary.avg_known_sum.calories, 150);
    assert.equal(result.summary.aggregation_scope, 'recorded_days_in_requested_range');
    assert.deepEqual(result, data.history);
  });
});

test('delete requests explicit v2 and accepts deleted legacy record', async () => {
  await withResponse({ record: data.legacy, message: 'deleted' }, async (calls) => {
    const result = await api.deleteNutritionRecordV2('https://example.test', 'user/a', 'old');
    assert.equal(calls[0].method, 'DELETE');
    assert.equal(calls[0].headers['X-Nutrition-Contract-Version'], '2');
    assert.deepEqual(result.record, data.legacy);
  });
});

test('version/revision failures retain typed server error and never retry as legacy', async () => {
  for (const code of ['upgrade_required', 'stale_revision', 'nutrition_flow_unavailable', 'legacy_conversion_required']) {
    await withResponse({ error: 'server message', error_code: code, required_nutrition_contract_version: 2 }, async (calls) => {
      await assert.rejects(api.previewNutritionRecordV2('https://example.test', data.payload), (error) =>
        error instanceof api.NutritionApiError && error.code === code && error.status === 409 &&
        error.requiredNutritionContractVersion === 2);
      assert.equal(calls.length, 1);
    }, 409);
  }
});

test('HTML error and network failures keep useful typed errors without including credentials', async () => {
  await withResponse('<html>proxy failed</html>', async () => {
    await assert.rejects(api.previewNutritionRecordV2('https://example.test', data.payload),
      (error) => error.status === 502 && error.code === 'http_error' && /502/.test(error.message));
  }, 502);
  const original = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error('secret transport details'); };
  try {
    await assert.rejects(api.previewNutritionRecordV2('https://example.test', data.payload),
      (error) => error.code === 'network_error' && !error.message.includes('secret'));
  } finally { globalThis.fetch = original; }
});

test('invalid success response cannot be cast into v2 including null-erasing missing keys', async () => {
  const missing = structuredClone(data.canonical);
  delete missing.foods[0].sugar;
  for (const canonical of [{}, { ...data.canonical, nutrition_contract_version: 1 }, missing]) {
    await withResponse({ record: canonical }, async () => {
      await assert.rejects(api.previewNutritionRecordV2('https://example.test', data.payload),
        (error) => error.code === 'invalid_response');
    });
  }
});

test('contradictory complete coverage and omitted unresolved IDs are rejected', async () => {
  const fakeComplete = structuredClone(data.canonical);
  fakeComplete.nutrition_context.coverage.nutrients.calories.status = 'complete';
  const missingIds = structuredClone(data.canonical);
  missingIds.nutrition_context.unresolved_item_ids = [];
  const incorrectSum = structuredClone(data.canonical);
  incorrectSum.total_calories = 0;
  for (const record of [fakeComplete, missingIds, incorrectSum]) {
    await withResponse({ record }, async () => {
      await assert.rejects(api.previewNutritionRecordV2('https://example.test', data.payload),
        (error) => error.code === 'invalid_response');
    });
  }
});

test('missing metadata or simultaneous point and exclusive bound cannot pass the response boundary', async () => {
  const missingSource = structuredClone(data.canonical);
  delete missingSource.foods[0].portion_source;
  const missingRiskIdentity = structuredClone(data.canonical);
  delete missingRiskIdentity.foods[0].allergens;
  const conflictingPoint = structuredClone(data.canonical);
  conflictingPoint.foods[0].nutrition_intake.values.sugar = 0.15;
  const conflictingWeight = structuredClone(data.canonical);
  conflictingWeight.foods[0].nutrition_intake.weight_g = 100;
  for (const record of [missingSource, missingRiskIdentity, conflictingPoint, conflictingWeight]) {
    await withResponse({ record }, async () => {
      await assert.rejects(api.previewNutritionRecordV2('https://example.test', data.payload),
        (error) => error.code === 'invalid_response');
    });
  }
});

test('snapshot uploads, nonfinite values and bad revision fail before fetch', async () => {
  let calls = 0;
  const original = globalThis.fetch;
  globalThis.fetch = async () => { calls += 1; throw new Error('must not fetch'); };
  try {
    for (const payload of [
      { ...data.payload, foods: data.record.foods },
      { ...data.payload, foods: [{ ...data.payload.foods[0], weight_g: NaN }] },
      { ...data.payload, base_revision: true },
    ]) {
      await assert.rejects(api.previewNutritionRecordV2('https://example.test', payload),
        (error) => error.code === 'invalid_request');
    }
    assert.equal(calls, 0);
  } finally { globalThis.fetch = original; }
});

test('original-cell client preview agrees with backend for the supported snapshot', () => {
  for (const food of data.record.foods) {
    assert.deepEqual(calculation.calculateNutritionPortion(food.nutrition_profile, food.weight_g, food.portion_source), food.nutrition_intake);
  }
  const coverage = calculation.aggregateNutritionCoverage(data.record.foods.map((item) => ({ ...item, profile: item.nutrition_profile })));
  assert.deepEqual(coverage, data.record.nutrition_context.coverage);
});
