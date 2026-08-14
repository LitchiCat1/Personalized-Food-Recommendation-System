import assert from 'node:assert/strict';
import test from 'node:test';
import { buildDietaryTrend, normalizeRecordDate } from '../lib/dietary-trends.ts';

const TAIPEI_OFFSET_MINUTES = -480;

function record(date, nutrients = {}, overrides = {}) {
  return {
    user_id: 'user-a',
    timestamp: `${date}T04:00:00Z`,
    total_calories: 100,
    total_protein: 10,
    total_carbs: 20,
    total_sugar: 3,
    total_fat: 5,
    total_saturated_fat: 1,
    total_trans_fat: 0,
    total_sodium: 200,
    total_fiber: 2,
    total_calcium: 100,
    total_iron: 1.5,
    ...nutrients,
    ...overrides,
  };
}

function build(records) {
  return buildDietaryTrend(records, {
    maxDays: 7,
    timezoneOffsetMinutes: TAIPEI_OFFSET_MINUTES,
    userId: 'user-a',
  });
}

test('normalizes timezone-aware and legacy UTC timestamps to the user calendar date', () => {
  assert.equal(normalizeRecordDate('2026-07-31T16:30:00Z', TAIPEI_OFFSET_MINUTES), '2026-08-01');
  assert.equal(normalizeRecordDate('2026-07-31T16:30:00', TAIPEI_OFFSET_MINUTES), '2026-08-01');
  assert.equal(normalizeRecordDate('not-a-date', TAIPEI_OFFSET_MINUTES), null);
});

test('shows one recorded day and aggregates every record on that local date', () => {
  const trend = build([
    record('2026-08-01'),
    record('2026-08-01', { total_calories: 250, total_protein: 12, total_sodium: 450 }),
  ]);

  assert.deepEqual(trend.daily.map((day) => day.date), ['2026-08-01']);
  assert.equal(trend.daily[0].record_count, 2);
  assert.equal(trend.daily[0].calories, 350);
  assert.equal(trend.daily[0].protein, 22);
  assert.equal(trend.daily[0].sugar, 6);
  assert.equal(trend.daily[0].calcium, 200);
  assert.equal(trend.daily[0].sodium, 650);
});

test('keeps two adjacent days in oldest-to-newest order', () => {
  const trend = build([record('2026-08-02'), record('2026-08-01')]);
  assert.deepEqual(trend.daily.map((day) => day.date), ['2026-08-01', '2026-08-02']);
});

test('does not bridge a missing date into the latest continuous segment', () => {
  const trend = build([record('2026-08-01'), record('2026-08-02'), record('2026-08-04')]);
  assert.deepEqual(trend.daily.map((day) => day.date), ['2026-08-04']);
});

test('limits a run longer than seven days to its newest seven dates', () => {
  const records = Array.from({ length: 8 }, (_, index) => record(`2026-08-${String(index + 1).padStart(2, '0')}`));
  const trend = build(records);
  assert.deepEqual(trend.daily.map((day) => day.date), [
    '2026-08-02',
    '2026-08-03',
    '2026-08-04',
    '2026-08-05',
    '2026-08-06',
    '2026-08-07',
    '2026-08-08',
  ]);
});

test('filters other users and falls back to food nutrients when record totals are absent', () => {
  const trend = build([
    record('2026-08-01', {
      total_calories: undefined,
      total_protein: undefined,
      total_carbs: undefined,
      total_fat: undefined,
      total_sodium: undefined,
      foods: [{ calories: 88, protein: 4, carbs: 12, fat: 3, sodium: 90 }],
    }),
    record('2026-08-01', { total_calories: 900 }, { user_id: 'user-b' }),
  ]);

  assert.equal(trend.daily[0].calories, 88);
  assert.equal(trend.daily[0].protein, 4);
  assert.equal(trend.summary.total_records, 1);
});
