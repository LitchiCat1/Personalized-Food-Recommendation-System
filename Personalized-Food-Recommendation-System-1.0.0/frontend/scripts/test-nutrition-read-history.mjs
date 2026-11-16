import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { loadNutritionModule } from './helpers/load-nutrition-module.mjs';
import { nutritionReadFixtures as data } from './helpers/nutrition-read-fixtures.mjs';

const { readNutritionHistory } = loadNutritionModule('nutrition-read-history');
const { assertNutritionCoverage } = loadNutritionModule('nutrition-response-validation');
const { roundNutritionMean } = loadNutritionModule('nutrition-calculation');
const api = loadNutritionModule('nutrition-record-api');

test('actual mixed history exposes reported known sums without complete means', () => {
  const model = readNutritionHistory(data.history);
  assert.equal(model.summary.avg_known_sum.calories, 150);
  assert.equal(model.summary.avg_value.calories, null);
  assert.equal(model.summary.nutrients.calories.known_value, null);
  assert.equal(model.summary.nutrients.calories.lower_bound, null);
  assert.equal(model.summary.coverage.nutrients.calories.legacy_items, 1);
  assert.equal(model.summary.coverage.nutrients.calories.eligible_items, 3);
});

test('actual empty server history keeps unknown averages and no invented zero day', () => {
  const model = readNutritionHistory(data.emptyHistory);
  assert.deepEqual(model.daily, []);
  assert.equal(model.summary.recorded_days, 0);
  assert.equal(model.summary.avg_known_sum.sodium, null);
  assert.equal(model.summary.avg_value.sodium, null);
  assert.equal(model.summary.nutrients.sodium.value, null);
});

test('complete day plus all-excluded day retains the conservative server summary', () => {
  const model = readNutritionHistory(data.excludedHistory);
  assert.equal(model.daily[0].nutrients.calories.value, 100);
  assert.equal(model.daily[1].nutrients.calories.value, null);
  assert.equal(model.summary.nutrients.calories.coverage.status, 'partial');
  assert.equal(model.summary.nutrients.calories.value, null);
  assert.equal(model.summary.avg_known_sum.calories, 50);
  assert.equal(model.summary.avg_value.calories, null);
});

test('decimal coverage means and compatibility float means preserve real Python rounding differences', () => {
  assert.equal(data.decimalHistory.summary.avg_known_sum.sodium, 0.1);
  assert.equal(data.decimalHistory.summary.avg_sodium, 0.2);
  const model = readNutritionHistory(data.decimalHistory);
  assert.equal(model.summary.avg_value.sodium, 0.1);
});

test('rounded means agree with Python on halfway, binary decimals and non-halfway values', () => {
  const cases = [[0.3, 2], [0.1 + 0.2, 2], [1.25, 1], [1.15, 1], [1.35, 1], [9.95, 1], [100, 3], [0, 1], [Number.MIN_VALUE, 1]];
  const expected = spawnSync('python', ['-c', 'import json,sys; print(json.dumps([round(x/n,1) for x,n in json.loads(sys.argv[1])]))', JSON.stringify(cases)], { encoding: 'utf8' });
  assert.equal(expected.status, 0, expected.stderr);
  assert.deepEqual(cases.map(([value, n]) => roundNutritionMean(value, n)), JSON.parse(expected.stdout));
});

test('daily and summary totals, counts, averages and coverage must describe the same scope', () => {
  const changes = [
    (v) => { v.daily[0].calories = 0; },
    (v) => { v.summary.total_records = 999; },
    (v) => { v.summary.recorded_days = 7; },
    (v) => { v.summary.avg_known_sum.calories = 0; },
    (v) => { v.summary.avg_calories = null; },
    (v) => { v.summary.avg_records_per_day = 9; },
    (v) => { v.summary.nutrition_coverage.nutrients.calories.known_sum += 1; },
    (v) => { v.summary.aggregation_scope = 'all_calendar_days'; },
    (v) => { v.daily[0].record_count = 0; },
  ];
  for (const change of changes) {
    const value = structuredClone(data.history);
    change(value);
    assert.throws(() => readNutritionHistory(value));
  }
});

test('duplicate, impossible or internally out-of-range history dates are rejected', () => {
  const duplicate = structuredClone(data.history);
  duplicate.daily.push(structuredClone(duplicate.daily[0]));
  assert.throws(() => readNutritionHistory(duplicate));
  const impossible = structuredClone(data.history);
  impossible.daily[0].date = '2026-02-29';
  assert.throws(() => readNutritionHistory(impossible));
  const span = structuredClone(data.excludedHistory);
  span.days = 1;
  assert.throws(() => readNutritionHistory(span));
  for (const days of [0, 366, 1.5, '7']) assert.throws(() => readNutritionHistory({ ...data.history, days }));
});

test('conservative history status cannot conceal incorrect daily aggregate evidence', () => {
  const value = structuredClone(data.excludedHistory);
  value.summary.nutrition_coverage.nutrients.calories.status = 'complete';
  assert.throws(() => readNutritionHistory(value));
});

test('coverage rejects contradictory denominator, bounds and empty known counts', () => {
  for (const mutate of [
    (c) => { c.nutrients.sodium.eligible_items += 1; c.nutrients.sodium.unresolved_items += 1; },
    (c) => { c.nutrients.sugar.known_bounds_sum = 0; c.nutrients.sugar.total_upper_bound = 0; },
    (c) => { c.nutrients.sugar.known_sum = 100; c.nutrients.sugar.total_upper_bound = 100.1; },
    (c) => { c.excluded_item_ids = ['food-a']; },
  ]) {
    const coverage = structuredClone(data.bounded.nutrition_context.coverage);
    mutate(coverage);
    assert.throws(() => assertNutritionCoverage(coverage));
  }
});

test('read history returns an independent snapshot', () => {
  const source = structuredClone(data.history);
  const model = readNutritionHistory(source);
  source.summary.avg_known_sum.calories = 999;
  model.daily[0].coverage.nutrients.calories.known_sum = 1;
  assert.equal(model.summary.avg_known_sum.calories, 150);
  assert.equal(source.daily[0].nutrition_coverage.nutrients.calories.known_sum, 150);
});

async function respond(body, run) {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify(body), { status: 200 });
  try { await run(); } finally { globalThis.fetch = original; }
}

test('v2 history transport validates complete scope and preserves its typed error boundary', async () => {
  const invalid = structuredClone(data.history);
  invalid.summary.avg_known_sum.calories = 0;
  await respond(invalid, async () => {
    await assert.rejects(api.fetchNutritionHistoryV2('https://example.test', 'read-user'), (e) =>
      e instanceof api.NutritionApiError && e.code === 'invalid_response');
  });
  await respond(data.excludedHistory, async () => {
    assert.deepEqual(await api.fetchNutritionHistoryV2('https://example.test', 'read-user'), data.excludedHistory);
  });
});

test('transport rejects valid history or records belonging to a different requested user/date', async () => {
  await respond(data.history, async () => {
    await assert.rejects(api.fetchNutritionHistoryV2('https://example.test', 'other-user'));
    await assert.rejects(api.fetchNutritionHistoryV2('https://example.test', 'read-user', 30));
  });
  await respond({ records: [data.complete], count: 1 }, async () => {
    await assert.rejects(api.fetchNutritionRecordsV2('https://example.test', 'other-user'));
    await assert.rejects(api.fetchNutritionRecordsV2('https://example.test', 'read-user', '2026-11-13'));
  });
});
