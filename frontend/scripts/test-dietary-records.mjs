import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildLocalTimestampForDate,
  calculateRecordFoodTotals,
  createManualRecordFoodDraft,
  createRecordFoodDrafts,
  filterAndSortRecords,
  formatDateInput,
  getDefaultRecordDateRange,
  parseDateInput,
  validateRecordDate,
  validateRecordDateRange,
  validateRecordFoodDrafts,
} from '../lib/dietary-records.ts';

const TAIPEI_OFFSET_MINUTES = -480;

function record(userId, clientRecordId, timestamp, overrides = {}) {
  return {
    user_id: userId,
    client_record_id: clientRecordId,
    timestamp,
    foods: [{ name: clientRecordId, calories: 100, protein: 10, carbs: 20, fat: 5, sodium: 200, fiber: 2 }],
    ...overrides,
  };
}

test('parses real slash or hyphen dates and rejects impossible calendar dates', () => {
  assert.equal(parseDateInput('2026/8/3'), '2026-08-03');
  assert.equal(parseDateInput(' 2026-12-31 '), '2026-12-31');
  assert.equal(parseDateInput('2026/02/29'), null);
  assert.equal(parseDateInput('not-a-date'), null);
});

test('validates same-day, cross-month and cross-year inclusive ranges', () => {
  for (const range of [
    { startDate: '2026/08/03', endDate: '2026/08/03' },
    { startDate: '2026/07/31', endDate: '2026/08/01' },
    { startDate: '2025/12/31', endDate: '2026/01/01' },
  ]) {
    assert.ok(validateRecordDateRange(range).dateKeys);
  }
  const reversed = validateRecordDateRange({ startDate: '2026/08/04', endDate: '2026/08/03' });
  assert.equal(reversed.dateKeys, null);
  assert.equal(reversed.errors.endDate, '結束日期不得早於開始日期');
});

test('builds a seven-day default range across a year boundary', () => {
  assert.deepEqual(getDefaultRecordDateRange(new Date(2026, 0, 3, 12)), {
    startDate: '2025/12/28',
    endDate: '2026/01/03',
  });
});

test('formats date picker values and validates today, past, future and leap dates', () => {
  const localNow = new Date(2026, 7, 4, 12, 30, 0);
  assert.equal(formatDateInput('2026-08-04'), '2026/08/04');
  assert.equal(validateRecordDate('2026/08/04', localNow).dateKey, '2026-08-04');
  assert.equal(validateRecordDate('2025/12/31', localNow).dateKey, '2025-12-31');
  assert.equal(validateRecordDate('2026/08/05', localNow).error, '紀錄日期不得晚於今天');
  assert.equal(validateRecordDate('2024/02/29', localNow).dateKey, '2024-02-29');
  assert.equal(validateRecordDate('2026/02/29', localNow).dateKey, null);
});

test('builds timezone-aware local timestamps without moving the selected calendar date', () => {
  const localNow = new Date(2026, 7, 4, 23, 58, 59, 123);
  for (const date of ['2024/02/29', '2025/12/31', '2026/01/01', '2026/07/31']) {
    const timestamp = buildLocalTimestampForDate(date, localNow);
    const dateKey = parseDateInput(date);
    assert.ok(timestamp.startsWith(`${dateKey}T23:58:59.123`));
    assert.match(timestamp, /[+-]\d{2}:\d{2}$/);
    assert.equal(filterAndSortRecords([
      record('user-a', dateKey, timestamp),
    ], 'user-a', dateKey, dateKey).length, 1);
  }
});

test('creates a blank manual draft and totals validated foods in the existing schema', () => {
  const draft = createManualRecordFoodDraft();
  assert.equal(draft.source, 'manual');
  assert.equal(draft.name, '');
  draft.name = '豆漿';
  for (const key of ['calories', 'protein', 'carbs', 'fat', 'sodium', 'fiber']) draft[key] = '1.25';
  const validation = validateRecordFoodDrafts([draft]);
  assert.ok(validation.foods);
  assert.deepEqual(calculateRecordFoodTotals(validation.foods), {
    calories: 1.25,
    protein: 1.25,
    carbs: 1.25,
    sugar: 0,
    fat: 1.25,
    saturated_fat: 0,
    trans_fat: 0,
    fiber: 1.25,
    sodium: 1.25,
    calcium: 0,
    iron: 0,
  });
  assert.equal(validation.foods[0].is_fried, false);
});

test('filters only the authenticated user and includes both local date boundaries', () => {
  const records = [
    record('user-a', 'end', '2026-08-02T16:30:00Z'),
    record('user-a', 'start', '2026-07-31T16:30:00Z'),
    record('user-a', 'outside', '2026-07-30T15:59:59Z'),
    record('user-b', 'other-user', '2026-08-01T12:00:00Z'),
  ];
  const result = filterAndSortRecords(records, 'user-a', '2026-08-01', '2026-08-03', TAIPEI_OFFSET_MINUTES);
  assert.deepEqual(result.map((item) => item.client_record_id), ['end', 'start']);
});

test('sorts records newest first with a stable client id tie-breaker', () => {
  const result = filterAndSortRecords([
    record('user-a', 'record-a', '2026-08-03T10:00:00Z'),
    record('user-a', 'record-c', '2026-08-03T12:00:00Z'),
    record('user-a', 'record-b', '2026-08-03T12:00:00Z'),
  ], 'user-a', '2026-08-03', '2026-08-03', TAIPEI_OFFSET_MINUTES);
  assert.deepEqual(result.map((item) => item.client_record_id), ['record-c', 'record-b', 'record-a']);
});

test('trims food names and accepts zero or positive decimal nutrients', () => {
  const drafts = createRecordFoodDrafts(record('user-a', 'record-a', '2026-08-03T10:00:00Z'));
  drafts[0].name = '  無糖豆漿  ';
  drafts[0].calories = '0';
  drafts[0].protein = '8.5';
  const validation = validateRecordFoodDrafts(drafts);
  assert.deepEqual(validation.errors, {});
  assert.equal(validation.foods?.[0].name, '無糖豆漿');
  assert.equal(validation.foods?.[0].calories, 0);
  assert.equal(validation.foods?.[0].protein, 8.5);
});

test('keeps draft content while reporting blank names, missing values and negative nutrients', () => {
  const drafts = createRecordFoodDrafts(record('user-a', 'record-a', '2026-08-03T10:00:00Z'));
  drafts[0].name = '   ';
  drafts[0].calories = '';
  drafts[0].sodium = '-1';
  const validation = validateRecordFoodDrafts(drafts);
  assert.equal(validation.foods, null);
  assert.equal(validation.errors['foods.0.name'], '食物名稱不可空白');
  assert.equal(validation.errors['foods.0.calories'], '熱量為必填');
  assert.equal(validation.errors['foods.0.sodium'], '鈉 (Sodium)需為 0 或正數');
  assert.equal(drafts[0].name, '   ');
});
