import assert from 'node:assert/strict';
import test from 'node:test';
import { loadNutritionModule } from './helpers/load-nutrition-module.mjs';
import { nutritionReadFixtures as fixtures } from './helpers/nutrition-read-fixtures.mjs';

const { readNutritionRecord } = loadNutritionModule('nutrition-read-model');
const { NUTRIENT_KEYS } = loadNutritionModule('nutrition-calculation');
const { summarizeNutritionRecords, aggregateReadCoverage, evaluateNutritionGoal } = loadNutritionModule('nutrition-read-aggregation');
const scope = (start = '2026-11-13', end = '2026-11-15', completeness = 'complete') => ({
  user_id: 'read-user', start_date: start, end_date: end, completeness,
});
function record(name, date = '2026-11-14', id = name) {
  const snapshot = structuredClone(fixtures[name]);
  snapshot.timestamp = `${date}T00:03:00+08:00`;
  snapshot.client_record_id = id;
  return readNutritionRecord(snapshot);
}

test('explicit calendar gaps remain no_records and averages use recorded days only', () => {
  const source = record('complete', '2026-11-13', 'first');
  const second = record('complete', '2026-11-15', 'second');
  const original = JSON.stringify([source, second]);
  const result = summarizeNutritionRecords([source, second], scope());
  assert.deepEqual(result.daily.map((day) => day.state), ['recorded', 'no_records', 'recorded']);
  assert.equal(result.daily[1].nutrients.calories.value, null);
  assert.equal(result.daily[1].nutrients.calories.known_value, null);
  assert.equal(result.daily[1].coverage.nutrients.calories.status, 'unknown');
  assert.equal(result.summary.recorded_days, 2);
  assert.equal(result.summary.calendar_days, 3);
  assert.equal(result.summary.total_records, 2);
  assert.equal(result.summary.avg_value.calories, source.nutrients.calories.value);
  assert.equal(result.summary.aggregation_scope, 'recorded_days_in_requested_range');
  assert.equal(JSON.stringify([source, second]), original);
});

test('empty ranges never become complete zero-intake evidence', () => {
  const result = summarizeNutritionRecords([], scope());
  assert.equal(result.summary.recorded_days, 0);
  assert.equal(result.summary.total_records, 0);
  for (const key of NUTRIENT_KEYS) {
    assert.equal(result.summary.coverage.nutrients[key].status, 'unknown');
    assert.equal(result.summary.avg_value[key], null);
    assert.equal(result.summary.avg_known_sum[key], null);
    assert.equal(result.summary.nutrients[key].known_value, null);
  }
  assert.equal(evaluateNutritionGoal(result.daily[0].nutrients.calories, 100, 'minimum_target').assessment, 'unknown');
});

test('confirmed zero is retained separately from missing data', () => {
  const result = summarizeNutritionRecords([record('complete')], scope());
  assert.equal(result.daily[1].nutrients.sodium.value, 0);
  assert.equal(result.daily[1].nutrients.sodium.known_value, 0);
  assert.equal(result.summary.avg_value.sodium, 0);
  assert.equal(result.daily[0].nutrients.sodium.value, null);
});

test('unresolved items remain denominator and a valid known excess remains visible', () => {
  const source = record('partial');
  const result = summarizeNutritionRecords([source], scope());
  const row = result.daily[1].nutrients.calories;
  assert.equal(row.coverage.eligible_items, 2);
  assert.equal(row.coverage.unresolved_items, 1);
  assert.equal(row.value, null);
  assert.equal(row.known_value, source.nutrients.calories.known_value);
  assert.equal(evaluateNutritionGoal(row, row.known_value / 2, 'upper_limit').assessment, 'known_excess');
  assert.equal(evaluateNutritionGoal(row, row.known_value * 2, 'minimum_target').assessment, 'unknown');
  assert.equal(evaluateNutritionGoal(row, row.known_value * 2, 'upper_limit').remaining, null);
});

test('exclusive bounds sum only when every consumed item has a point or bound', () => {
  const one = record('bounded', '2026-11-14', 'bound-one');
  const two = record('bounded', '2026-11-14', 'bound-two');
  const result = summarizeNutritionRecords([one, two], scope());
  const row = result.daily[1].nutrients.sugar;
  assert.equal(row.value, null);
  assert.equal(row.upper_bound, one.nutrients.sugar.upper_bound * 2);
  assert.equal(row.upper_bound_comparison, 'less_than');
  assert.equal(row.coverage.bounded_items, 2);
  assert.equal(evaluateNutritionGoal(row, 1, 'upper_limit').assessment, 'unknown');
  const missingPage = summarizeNutritionRecords([], scope('2026-11-14', '2026-11-14', 'page'));
  assert.equal(missingPage.daily[0].state, 'not_loaded');
  assert.equal(missingPage.daily[0].nutrients.calories.value, null);
  const unresolved = summarizeNutritionRecords([one, record('unknown')], scope()).daily[1].nutrients.sugar;
  assert.equal(unresolved.upper_bound, null);
  assert.equal(unresolved.coverage.bounded_items, 1);
  assert.equal(unresolved.coverage.eligible_items, 2);
});

test('legacy reported totals remain separate from validated points in mixed scopes', () => {
  const modern = record('complete');
  const legacy = record('legacy');
  const result = summarizeNutritionRecords([modern, legacy], scope());
  const row = result.daily[1].nutrients.calories;
  assert.equal(row.coverage.status, 'legacy_unknown');
  assert.equal(row.known_value, modern.nutrients.calories.known_value);
  assert.equal(row.reported_value, legacy.nutrients.calories.reported_value);
  assert.equal(row.coverage.known_sum, row.known_value + row.reported_value);
  assert.equal(row.value, null);
  assert.equal(row.lower_bound, null);
  assert.equal(result.summary.avg_known_value.calories, row.known_value);
  assert.equal(result.summary.avg_reported_value.calories, row.reported_value);
  assert.equal(evaluateNutritionGoal(row, 1, 'upper_limit').assessment, 'unknown');
});

test('missing legacy totals are absent observations even when coverage carries a zero subtotal', () => {
  const snapshot = structuredClone(fixtures.legacy);
  delete snapshot.total_sodium;
  const result = summarizeNutritionRecords([readNutritionRecord(snapshot)], scope());
  assert.equal(result.summary.coverage.nutrients.sodium.known_sum, 0);
  assert.equal(result.summary.nutrients.sodium.reported_value, null);
  assert.equal(result.summary.nutrients.sodium.known_value, null);
  assert.equal(result.summary.avg_reported_value.sodium, null);
  assert.equal(result.summary.avg_value.sodium, null);
});

test('incomplete pages retain observed data without whole-day or average conclusions', () => {
  const result = summarizeNutritionRecords([record('complete')], scope('2026-11-14', '2026-11-14', 'page'));
  const row = result.daily[0].nutrients.calories;
  assert.equal(row.coverage.status, 'complete');
  assert.equal(row.scope_complete, false);
  assert.equal(row.value, null);
  assert.equal(row.lower_bound, null);
  assert.equal(row.upper_bound, null);
  assert.ok(row.known_value > 0);
  assert.equal(result.summary.avg_known_sum.calories, null);
  assert.equal(result.summary.avg_known_value.calories, null);
  assert.equal(evaluateNutritionGoal(row, 1, 'upper_limit').assessment, 'unknown');
});

test('all-excluded meals do not poison another consumed meal but an excluded-only day remains unknown', () => {
  const normal = record('complete', '2026-11-13');
  const excludedSameDay = record('excluded', '2026-11-13', 'same-day-excluded');
  const together = summarizeNutritionRecords([normal, excludedSameDay], scope());
  assert.equal(together.daily[0].nutrients.calories.coverage.status, 'complete');
  const separate = summarizeNutritionRecords([normal, record('excluded')], scope());
  assert.equal(separate.daily[1].state, 'recorded');
  assert.equal(separate.daily[1].nutrients.calories.coverage.eligible_items, 0);
  assert.equal(separate.daily[1].nutrients.calories.value, null);
  assert.equal(separate.summary.recorded_days, 2);
  assert.equal(separate.summary.nutrients.calories.coverage.status, 'partial');
  assert.equal(separate.summary.nutrients.calories.value, null);
  assert.equal(separate.summary.avg_value.calories, null);
});

test('an excluded-only recorded day prevents a multi-day exclusive total bound', () => {
  const result = summarizeNutritionRecords([record('bounded', '2026-11-13'), record('excluded')], scope());
  assert.ok(result.daily[0].nutrients.sugar.upper_bound > 0);
  assert.equal(result.summary.nutrients.sugar.upper_bound, null);
  assert.equal(result.summary.nutrients.sugar.upper_bound_comparison, null);
});

test('local date prefix survives a UTC day boundary and leap dates are grouped literally', () => {
  const result = summarizeNutritionRecords([record('complete', '2024-02-29')], scope('2024-02-28', '2024-03-01'));
  assert.deepEqual(result.daily.map((day) => day.date), ['2024-02-28', '2024-02-29', '2024-03-01']);
  assert.equal(result.daily[1].record_count, 1);
});

test('rejects mixed users, out-of-range dates, duplicate stable IDs and invalid ranges', () => {
  const foreign = structuredClone(fixtures.complete);
  foreign.user_id = 'other-user';
  for (const [records, range] of [
    [[readNutritionRecord(foreign)], scope()],
    [[record('complete', '2026-11-12')], scope()],
    [[record('complete'), record('complete')], scope()],
    [[], scope('2026-02-30', '2026-03-01')],
    [[], scope('2026-11-15', '2026-11-13')],
    [[], scope('2025-01-01', '2026-12-31')],
    [[], { ...scope(), user_id: '' }],
    [[], { ...scope(), completeness: undefined }],
  ]) assert.throws(() => summarizeNutritionRecords(records, range));
});

test('aggregation reconstructs validated snapshots instead of trusting modified read projections', () => {
  const input = record('partial');
  input.nutrients.calories.value = 0;
  input.nutrients.calories.coverage.known_sum = 0;
  const result = summarizeNutritionRecords([input], scope());
  assert.equal(result.daily[1].nutrients.calories.value, null);
  assert.ok(result.daily[1].nutrients.calories.known_value > 0);
  input.record.total_calories = 0;
  assert.throws(() => summarizeNutritionRecords([input], scope()));
});

test('only complete values support within-limit or shortfall statements', () => {
  const row = summarizeNutritionRecords([record('complete')], scope()).daily[1].nutrients.calories;
  assert.equal(evaluateNutritionGoal(row, row.value, 'upper_limit').assessment, 'within_limit');
  assert.equal(evaluateNutritionGoal(row, row.value, 'upper_limit').remaining, 0);
  assert.equal(evaluateNutritionGoal(row, row.value, 'minimum_target').assessment, 'target_met');
  assert.equal(evaluateNutritionGoal(row, row.value + 10, 'minimum_target').shortfall, 10);
  for (const target of [NaN, Infinity, -1, null, '100']) {
    assert.throws(() => evaluateNutritionGoal(row, target, 'upper_limit'));
  }
});

test('numeric overflow fails explicitly instead of producing an infinite total', () => {
  const first = structuredClone(fixtures.legacy);
  const second = structuredClone(fixtures.legacy);
  first.total_calories = Number.MAX_VALUE;
  second.total_calories = Number.MAX_VALUE;
  first.client_record_id = 'huge-first';
  second.client_record_id = 'huge-second';
  assert.throws(() => summarizeNutritionRecords([readNutritionRecord(first), readNutritionRecord(second)], scope()));
});

test('cross-record coverage does not concatenate colliding per-meal food IDs', () => {
  const first = record('complete', '2026-11-14', 'meal-one');
  const second = record('complete', '2026-11-14', 'meal-two');
  const coverage = aggregateReadCoverage([first.coverage, second.coverage]);
  assert.equal(coverage.nutrients.calories.eligible_items, 2);
  assert.equal(coverage.included_item_ids, undefined);
  assert.equal(coverage.excluded_item_ids, undefined);
});

test('re-aggregating conservative summaries does not restore a suppressed complete or bound claim', () => {
  const complete = summarizeNutritionRecords([record('complete', '2026-11-13'), record('excluded')], scope());
  assert.equal(aggregateReadCoverage([complete.summary.coverage]).nutrients.calories.status, 'partial');
  const bounded = summarizeNutritionRecords([record('bounded', '2026-11-13'), record('excluded')], scope());
  assert.equal(aggregateReadCoverage([bounded.summary.coverage]).nutrients.sugar.total_upper_bound, null);
});
