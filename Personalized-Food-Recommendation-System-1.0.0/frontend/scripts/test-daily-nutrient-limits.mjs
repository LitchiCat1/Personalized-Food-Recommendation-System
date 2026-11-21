import test from 'node:test';
import assert from 'node:assert/strict';
import {
  parseDailyLimitInput, resolveDailyLimitDraft, stepDailyLimitValue,
} from '../lib/daily-nutrient-limits.ts';

const carbs = {
  unit: 'g', min: 0, max: 1000, step: 1, precision: 1, default_value: 250,
  value: 250, source: 'default', active: true, effective_value: 250, effective_condition_ids: ['diabetes'],
};
const sugar = { ...carbs, max: 500, value: 10.5, source: 'custom' };
const sodium = { ...carbs, unit: 'mg', max: 10000, step: 1, precision: 0, default_value: 1500, value: 1500 };

test('accepts zero and values within server bounds and decimal precision', () => {
  assert.equal(parseDailyLimitInput('0', carbs), 0);
  assert.equal(parseDailyLimitInput('999.9', carbs), 999.9);
  assert.equal(parseDailyLimitInput('1000', carbs), 1000);
  for (const input of ['', ' ', '-0.1', '1000.1', '1.05', '1e2', 'NaN', 'Infinity']) {
    assert.equal(parseDailyLimitInput(input, carbs), null);
  }
  assert.equal(parseDailyLimitInput('1.5', sodium), null);
});

test('steps by 1 g without dropping a fractional value and clamps to the server range', () => {
  assert.equal(stepDailyLimitValue('0.2', 1, carbs), '1.2');
  assert.equal(stepDailyLimitValue('1.2', -1, carbs), '0.2');
  assert.equal(stepDailyLimitValue('0.2', -1, carbs), '0');
  assert.equal(stepDailyLimitValue('999.5', 1, carbs), '1000');
  assert.equal(stepDailyLimitValue('0', -1, carbs), '0');
  assert.equal(stepDailyLimitValue('1000', 1, carbs), '1000');
  assert.equal(stepDailyLimitValue('1500', -1, sodium), '1499');
  assert.equal(stepDailyLimitValue('', -1, sodium), null);
});

test('sends only custom settings, distinguishes zero and reset, and retains inactive custom settings', () => {
  const inactiveSugar = { ...sugar, active: false };
  assert.deepEqual(resolveDailyLimitDraft({}, { carbs, sugar: inactiveSugar }), { sugar: 10.5 });
  assert.deepEqual(resolveDailyLimitDraft({ carbs: '0', sugar: null }, { carbs, sugar }), { carbs: 0 });
  assert.deepEqual(resolveDailyLimitDraft({ sugar: null }, { carbs, sugar }), {});
  assert.equal(resolveDailyLimitDraft({ sugar: '' }, { carbs, sugar }), null);
});
