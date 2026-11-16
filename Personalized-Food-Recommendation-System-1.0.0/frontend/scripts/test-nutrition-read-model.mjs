import assert from 'node:assert/strict';
import test from 'node:test';
import { loadNutritionModule } from './helpers/load-nutrition-module.mjs';
import { nutritionReadFixtures as data } from './helpers/nutrition-read-fixtures.mjs';

const { readNutritionRecord, parseNutritionDate } = loadNutritionModule('nutrition-read-model');
const { sumNutritionNumbers } = loadNutritionModule('nutrition-calculation');

test('actual complete server record preserves an exact zero and local Taiwan date', () => {
  const model = readNutritionRecord(data.complete);
  assert.equal(model.date, '2026-11-14');
  assert.equal(new Date(model.timestamp).toISOString().slice(0, 10), '2026-11-13');
  assert.equal(model.nutrients.sodium.value, 0);
  assert.equal(model.nutrients.sodium.known_value, 0);
  assert.equal(model.nutrients.sodium.reported_value, null);
  assert.equal(model.nutrients.calories.value, 100);
});

test('unresolved included items preserve the denominator without a false full total', () => {
  const model = readNutritionRecord(data.partial);
  assert.equal(model.nutrients.calories.value, null);
  assert.equal(model.nutrients.calories.known_value, 100);
  assert.equal(model.nutrients.calories.lower_bound, 100);
  assert.equal(model.nutrients.calories.coverage.eligible_items, 2);
  assert.deepEqual(model.record.nutrition_context.unresolved_item_ids, ['food-b']);
  assert.equal(model.record.foods[1].weight_g, null);
});

test('exclusive label upper bound stays separate from exact intake', () => {
  const model = readNutritionRecord(data.bounded);
  assert.equal(model.nutrients.sugar.value, null);
  assert.equal(model.nutrients.sugar.known_value, null);
  assert.equal(model.nutrients.sugar.upper_bound, 0.1);
  assert.equal(model.nutrients.sugar.upper_bound_comparison, 'less_than');
});

test('unknown and all-excluded snapshots never become confirmed zero intake', () => {
  for (const record of [data.unknown, data.excluded]) {
    const model = readNutritionRecord(record);
    for (const row of Object.values(model.nutrients)) {
      assert.equal(row.value, null);
      assert.equal(row.known_value, null);
      assert.equal(row.lower_bound, null);
    }
  }
  assert.equal(readNutritionRecord(data.excluded).coverage.nutrients.calories.eligible_items, 0);
});

test('legacy totals retain reported values without gaining validated point status', () => {
  const model = readNutritionRecord(data.legacy);
  assert.equal(model.contract_version, 1);
  assert.equal(model.nutrients.calories.reported_value, 50);
  assert.equal(model.nutrients.sodium.reported_value, 0);
  assert.equal(model.nutrients.protein.reported_value, null);
  assert.equal(model.nutrients.calories.known_value, null);
  assert.equal(model.nutrients.calories.lower_bound, null);
  assert.equal(model.nutrients.calories.value, null);
  assert.equal(model.nutrients.calories.coverage.status, 'legacy_unknown');
  assert.equal(model.coverage.nutrients.calories.known_sum, 50);
});

test('legacy records with no foods retain one unresolved placeholder', () => {
  const model = readNutritionRecord({ user_id: 'u', timestamp: '2026-11-14T01:00:00' });
  assert.equal(model.coverage.nutrients.calories.eligible_items, 1);
  assert.equal(model.nutrients.calories.reported_value, null);
  const unusedAlias = structuredClone(data.legacy);
  unusedAlias.foods[0].sugar = 2;
  unusedAlias.foods[0].refined_sugar = '2';
  assert.equal(readNutritionRecord(unusedAlias).nutrients.sugar.reported_value, null);
});

test('projection snapshots preserve profiles, context and original identity independently of source mutation', () => {
  const source = structuredClone(data.complete);
  source.foods[0].original_food_identity = { name: 'original rice' };
  const model = readNutritionRecord(source);
  source.foods[0].nutrition_profile.source_nutrients.calories.value = '999';
  assert.equal(model.record.foods[0].nutrition_profile.source_nutrients.calories.value, '100');
  assert.equal(model.record.foods[0].original_food_identity.name, 'original rice');
  model.record.foods[0].name = 'changed local copy';
  assert.equal(source.foods[0].name, 'rice');
});

test('malformed legacy numbers and future versions are rejected instead of downgraded', () => {
  for (const change of [{ total_calories: null }, { total_calories: NaN }, { total_calories: -1 },
    { total_calories: '0' }, { nutrition_contract_version: 3 }, { foods: {} }, { user_id: '' }]) {
    assert.throws(() => readNutritionRecord({ ...data.legacy, ...change }));
  }
});

test('impossible timestamps and calendar dates cannot be silently normalized', () => {
  for (const timestamp of ['2026-02-29T00:00:00+08:00', '2026-11-14T25:00:00', '']) {
    assert.throws(() => readNutritionRecord({ ...data.complete, timestamp }));
  }
  assert.equal(parseNutritionDate('2024-02-29'), '2024-02-29');
  assert.equal(readNutritionRecord({ ...data.legacy, timestamp: '2026-11-14' }).date, '2026-11-14');
  for (const date of ['2026-02-29', '2026-13-01', '2026-11-31', '0000-01-01', '26-11-14']) {
    assert.throws(() => parseNutritionDate(date));
  }
});

test('forged totals or inconsistent profile snapshots do not enter the read model', () => {
  const fake = structuredClone(data.complete);
  fake.total_calories = 1;
  assert.throws(() => readNutritionRecord(fake));
  const omitted = structuredClone(data.partial);
  omitted.foods.pop();
  assert.throws(() => readNutritionRecord(omitted));
});

test('aggregation arithmetic uses decimal observations once and rejects overflow', () => {
  assert.equal(sumNutritionNumbers([0.1, 0.2]), 0.3);
  assert.equal(sumNutritionNumbers([]), 0);
  assert.throws(() => sumNutritionNumbers([Number.MAX_VALUE, Number.MAX_VALUE]));
  assert.throws(() => sumNutritionNumbers([null]));
});
