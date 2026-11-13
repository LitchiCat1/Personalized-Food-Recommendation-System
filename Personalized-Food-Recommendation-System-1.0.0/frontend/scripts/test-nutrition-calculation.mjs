import assert from 'node:assert/strict';
import test from 'node:test';
import {
  aggregateNutritionCoverage,
  calculateNutritionPortion,
  formatNutritionMeasurement,
  NUTRIENT_KEYS,
  NutritionCalculationError,
} from '../lib/nutrition-calculation.ts';

const cell = (value, unit = 'g', comparison = 'exact') => ({ value: String(value), unit, comparison, label_rounding: null });
function profile(overrides = {}, basis = { basis: 'per_100g', weight_g: '100', volume_ml: null }) {
  const source = Object.fromEntries(NUTRIENT_KEYS.map((key) => [key, null]));
  Object.assign(source, overrides);
  return {
    schema_version: 'NutritionProfileV1',
    basis: basis.basis,
    basis_weight_g: Number(basis.weight_g),
    basis_volume_ml: basis.volume_ml === null ? null : Number(basis.volume_ml),
    source_basis: basis,
    source_nutrients: source,
    source_details: { source_type: 'test_fixture' },
    per_100g: Object.fromEntries(NUTRIENT_KEYS.map((key) => [key, 999])),
    upper_bounds_per_100g: Object.fromEntries(NUTRIENT_KEYS.map((key) => [key, null])),
  };
}
const item = (id, snapshot, weight = 100, extra = {}) => ({
  item_id: id, profile: snapshot, weight_g: weight, portion_source: 'user_weighed', ...extra,
});
function errorCode(code) {
  return (error) => error instanceof NutritionCalculationError && error.code === code;
}

test('calculates all nine nullable fields without replacing missing values with zero', () => {
  const snapshot = profile({ calories: cell('100', 'kcal'), protein: cell('0'), sugar: cell('0.1', 'g', 'less_than') });
  const result = calculateNutritionPortion(snapshot, 200, 'user_adjusted');
  assert.deepEqual(Object.keys(result.values), [...NUTRIENT_KEYS]);
  assert.equal(result.values.calories, 200);
  assert.equal(result.values.protein, 0);
  assert.equal(result.values.sugar, null);
  assert.equal(result.upper_bounds.sugar, 0.2);
  assert.equal(result.values.sodium, null);
  assert.equal(result.upper_bounds.sodium, null);
  assert.deepEqual(result.missing_nutrition_fields, NUTRIENT_KEYS.filter((key) => !['calories', 'protein'].includes(key)));
  assert.equal(result.portion_source, 'user_adjusted');
});

test('weight edits always return to original cells and never scale displayed numbers', () => {
  const snapshot = profile({ calories: cell('400', 'kcal'), sodium: cell('3.333', 'mg') },
    { basis: 'per_serving', weight_g: '200', volume_ml: null });
  const original = JSON.stringify(snapshot);
  for (const weight of [200, 120, 270, 85, 100, 120.5, 200]) {
    const result = calculateNutritionPortion(snapshot, weight, 'user_adjusted');
    assert.equal(result.values.calories, weight * 2);
  }
  assert.equal(calculateNutritionPortion(snapshot, 200).values.sodium, 3.333);
  assert.equal(JSON.stringify(snapshot), original);
  assert.deepEqual(calculateNutritionPortion(JSON.parse(original), 200), calculateNutritionPortion(snapshot, 200));
});

test('unknown weight or profile retains unknown intake and never assumes 100 grams', () => {
  const snapshot = profile({ calories: cell('100', 'kcal') });
  for (const [source, weight] of [[snapshot, null], [null, 200], [null, null]]) {
    const result = calculateNutritionPortion(source, weight);
    assert.ok(Object.values(result.values).every((value) => value === null));
    assert.equal(result.weight_g, weight);
    assert.deepEqual(result.missing_nutrition_fields, [...NUTRIENT_KEYS]);
  }
});

test('converts original kJ and mass units directly before terminal number conversion', () => {
  const snapshot = profile({ calories: cell('418.4', 'kJ'), sodium: cell('0.08'), protein: cell('1500', 'mg'), fiber: cell('1250000', 'ug') });
  const result = calculateNutritionPortion(snapshot, 300);
  assert.equal(result.values.calories, 300);
  assert.equal(result.values.sodium, 240);
  assert.equal(result.values.protein, 4.5);
  assert.equal(result.values.fiber, 3.75);
});

test('a 100ml source requires an explicit evidenced gram weight', () => {
  const basis = { basis: 'per_100ml', weight_g: '103', volume_ml: '100' };
  const snapshot = profile({ calories: cell('61', 'kcal') }, basis);
  assert.equal(calculateNutritionPortion(snapshot, 206).values.calories, 122);
  assert.throws(() => calculateNutritionPortion(profile({}, { ...basis, weight_g: null }), 100));
  assert.throws(() => calculateNutritionPortion(profile({}, { ...basis, volume_ml: null }), 100), errorCode('invalid_profile'));
  assert.throws(() => calculateNutritionPortion(profile({}, { ...basis, volume_ml: '200' }), 100), errorCode('invalid_profile'));
});

test('coverage retains unmatched items and unknown-weight items in every denominator', () => {
  const snapshot = profile({ calories: cell('100', 'kcal'), protein: cell('0') });
  const coverage = aggregateNutritionCoverage([item('matched', snapshot), item('unmatched', null), item('unknown-weight', snapshot, null)]);
  assert.deepEqual(coverage.included_item_ids, ['matched', 'unmatched', 'unknown-weight']);
  assert.equal(coverage.nutrients.calories.eligible_items, 3);
  assert.equal(coverage.nutrients.calories.known_items, 1);
  assert.equal(coverage.nutrients.calories.unresolved_items, 2);
  assert.equal(coverage.nutrients.calories.known_sum, 100);
  assert.equal(coverage.nutrients.calories.status, 'partial');
  assert.equal(coverage.nutrients.protein.known_sum, 0);
  assert.equal(coverage.nutrients.protein.known_items, 1);
  assert.equal(coverage.nutrients.sodium.known_items, 0);
  assert.equal(coverage.nutrients.sodium.status, 'unknown');
});

test('coverage treats same-name foods separately and removes only explicit not_consumed', () => {
  const snapshot = profile({ calories: cell('100', 'kcal') });
  const coverage = aggregateNutritionCoverage([
    item('first', snapshot, 100, { name: 'same' }), item('second', snapshot, 200, { name: 'same' }),
    item('excluded', null, null, { included: false, exclusion_reason: 'not_consumed' }),
  ]);
  assert.equal(coverage.nutrients.calories.known_sum, 300);
  assert.equal(coverage.nutrients.calories.eligible_items, 2);
  assert.equal(coverage.nutrients.calories.status, 'complete');
  assert.deepEqual(coverage.excluded_item_ids, ['excluded']);
  assert.throws(() => aggregateNutritionCoverage([item('x', snapshot), item('x', snapshot)]), errorCode('invalid_items'));
  assert.throws(() => aggregateNutritionCoverage([item('x', null, null, { included: false })]), errorCode('invalid_items'));
  assert.throws(() => aggregateNutritionCoverage([item('x', null, null, { included: 'false' })]), errorCode('invalid_items'));
});

test('bound-only items remain unresolved point values and produce a total bound only with full bound coverage', () => {
  const exact = profile({ sugar: cell('10') });
  const bounded = profile({ sugar: cell('0.1', 'g', 'less_than') });
  const coverage = aggregateNutritionCoverage([item('point', exact), item('bound', bounded)]);
  const sugar = coverage.nutrients.sugar;
  assert.equal(sugar.known_sum, 10);
  assert.equal(sugar.known_bounds_sum, 0.1);
  assert.equal(sugar.total_upper_bound, 10.1);
  assert.equal(sugar.upper_bound_comparison, 'less_than');
  assert.equal(sugar.unresolved_items, 1);
  assert.equal(sugar.status, 'partial');
  const unknown = aggregateNutritionCoverage([item('point', exact), item('bound', bounded), item('unknown', null)]);
  assert.equal(unknown.nutrients.sugar.total_upper_bound, null);
  assert.equal(unknown.nutrients.sugar.upper_bound_comparison, null);
});

test('empty and fully excluded coverage remains unknown', () => {
  for (const items of [[], [item('excluded', null, null, { included: false, exclusion_reason: 'not_consumed' })]]) {
    const coverage = aggregateNutritionCoverage(items);
    assert.equal(coverage.nutrients.calories.status, 'unknown');
    assert.equal(coverage.nutrients.calories.eligible_items, 0);
    assert.equal(coverage.nutrients.calories.total_upper_bound, null);
  }
});

test('sums decimal source cells without accumulating binary floating point drift', () => {
  const snapshot = profile({ sodium: cell('0.1', 'mg') });
  const coverage = aggregateNutritionCoverage(Array.from({ length: 10 }, (_, index) => item(String(index), snapshot)));
  assert.equal(coverage.nutrients.sodium.known_sum, 1);
});

test('invalid weights, units, comparisons and source bases fail explicitly', () => {
  const snapshot = profile({ calories: cell('100', 'kcal') });
  for (const weight of [0, -1, true, '100', NaN, Infinity]) {
    assert.throws(() => calculateNutritionPortion(snapshot, weight));
  }
  assert.throws(() => calculateNutritionPortion(snapshot, 100, 'unverified'), errorCode('invalid_portion'));
  assert.throws(() => calculateNutritionPortion(profile({ protein: cell('1', 'kcal') }), 100), errorCode('invalid_profile'));
  assert.throws(() => calculateNutritionPortion(profile({ protein: cell('1', 'toString') }), 100), errorCode('invalid_profile'));
  assert.throws(() => calculateNutritionPortion(undefined, 100), errorCode('invalid_profile'));
  assert.throws(() => calculateNutritionPortion(profile({ calories: cell('1', 'g') }), 100), errorCode('invalid_profile'));
  assert.throws(() => calculateNutritionPortion(profile({ protein: cell('1', 'g', 'approximately') }), 100), errorCode('invalid_profile'));
  assert.throws(() => calculateNutritionPortion(profile({ protein: cell('0', 'g', 'less_than') }), 100));
  assert.throws(() => calculateNutritionPortion(profile({}, { basis: 'per_100g', weight_g: '200', volume_ml: null }), 100), errorCode('invalid_profile'));
  const missing = profile();
  delete missing.source_nutrients.sodium;
  assert.throws(() => calculateNutritionPortion(missing, 100), errorCode('invalid_profile'));
});

test('decimal numeric strings remain strict rather than coercing booleans, signs or spaces', () => {
  for (const value of [true, ' 1', '+1', '-0', '01', 'NaN', 'Infinity', '1e9999999', '1e-9999999']) {
    assert.throws(() => calculateNutritionPortion(profile({ protein: { value, unit: 'g', comparison: 'exact' } }), 100));
  }
});

test('finite extreme ratios survive intermediate overflow while final overflow and underflow fail', () => {
  const tiny = profile({ sodium: cell('1e-300', 'mg') }, { basis: 'per_serving', weight_g: '1e-300', volume_ml: null });
  assert.equal(calculateNutritionPortion(tiny, 100).values.sodium, 100);
  const huge = profile({ sodium: cell('1e308', 'mg') }, { basis: 'per_serving', weight_g: '1e308', volume_ml: null });
  assert.equal(calculateNutritionPortion(huge, 100).values.sodium, 100);
  assert.throws(() => calculateNutritionPortion(profile({ sodium: cell('1e308', 'mg') }), 1000), errorCode('numeric_range'));
  assert.throws(() => calculateNutritionPortion(profile({ sodium: cell('5e-324', 'mg') }), Number.MIN_VALUE), errorCode('numeric_range'));
  const maximum = profile({ sodium: cell(String(Number.MAX_VALUE), 'mg') });
  assert.equal(calculateNutritionPortion(maximum, 100).values.sodium, Number.MAX_VALUE);
  assert.throws(() => aggregateNutritionCoverage([item('a', maximum), item('b', maximum)]), errorCode('numeric_range'));
});

test('a combined total upper bound is also checked for overflow', () => {
  const exact = profile({ sodium: cell('1e308', 'mg') });
  const bounded = profile({ sodium: cell('1e308', 'mg', 'less_than') });
  assert.throws(() => aggregateNutritionCoverage([item('point', exact), item('bound', bounded)]), errorCode('numeric_range'));
});

test('formatting distinguishes exact zero, unknown, and exclusive bounds without rounding a bound down', () => {
  assert.equal(formatNutritionMeasurement(0, null, 'g'), '0 g');
  assert.equal(formatNutritionMeasurement(null, null, 'g'), '未知');
  assert.equal(formatNutritionMeasurement(null, 0.1, 'g'), '<0.1 g');
  assert.equal(formatNutritionMeasurement(null, 0.000001, 'g'), '<0.000001 g');
  assert.throws(() => formatNutritionMeasurement(0, 0.1), errorCode('invalid_profile'));
  assert.throws(() => formatNutritionMeasurement(null, 0), errorCode('invalid_profile'));
  assert.throws(() => formatNutritionMeasurement(Infinity, null), errorCode('invalid_number'));
});
