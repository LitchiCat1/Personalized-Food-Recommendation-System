import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildOCRDetectedFood,
  FOOD_NAME_REQUIRED_MESSAGE,
  normalizeFoodName,
  saveRecord,
} from '../lib/scanner.ts';
import { getAutoMealType, normalizeMealType, perMealBudget } from '../lib/meal.ts';

function detectedFood(name = '原始名稱') {
  return {
    id: 'ocr-test',
    foodName: name,
    confidence: 100,
    source: 'nutrition-label-ocr',
    needsConfirmation: false,
    boundingBox: { x: 0, y: 0, w: 0, h: 0 },
    estimatedWeight: 100,
    nutrition: {
      calories: 180,
      protein: 8.5,
      carbs: 22,
      sugar: 4.5,
      fat: 6,
      saturated_fat: 1.2,
      trans_fat: 0,
      sodium: 210,
      fiber: 3,
      is_fried: true,
    },
    gi: 'medium',
    allergens: [],
    warnings: [],
  };
}

test('normalizes the final OCR food name and carries it into detected food', () => {
  assert.equal(normalizeFoodName('  修改後豆漿  '), '修改後豆漿');
  assert.equal(normalizeFoodName('   '), '');
  assert.equal(buildOCRDetectedFood({
    product_name: '  修改後豆漿  ',
    serving_size_g: 250,
    nutrition_per_serving: { calories: 180, protein: 8.5, carbs: 22, fat: 6, sodium: 210, fiber: 3 },
  }).foodName, '修改後豆漿');
  assert.throws(() => buildOCRDetectedFood({ product_name: '   ' }), new RegExp(FOOD_NAME_REQUIRED_MESSAGE));
});

test('saves the user final trimmed name in the existing foods schema', async () => {
  const originalFetch = globalThis.fetch;
  let requestBody;
  globalThis.fetch = async (_url, init) => {
    requestBody = JSON.parse(init.body);
    return { ok: true, json: async () => ({}) };
  };
  try {
    await saveRecord({
      apiBaseUrl: 'https://api.example.test',
      userId: 'user-a',
      clientRecordId: 'edited-name-record',
      foods: [detectedFood('  使用者最後輸入名稱  ')],
      source: 'nutrition-label',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(requestBody.foods[0].name, '使用者最後輸入名稱');
  assert.equal(requestBody.foods[0].calories, 180);
  assert.equal(requestBody.foods[0].sugar, 4.5);
  assert.equal(requestBody.foods[0].is_fried, true);
  assert.equal(requestBody.total_saturated_fat, 1.2);
  assert.equal(requestBody.source, 'nutrition-label');
  assert.equal(requestBody.client_record_id, 'edited-name-record');
});

test('deduplicates rapid matching saves and releases the lock after failure for retry', async () => {
  const originalFetch = globalThis.fetch;
  let requestCount = 0;
  let releaseFirstRequest;
  globalThis.fetch = () => {
    requestCount += 1;
    return new Promise((resolve) => {
      releaseFirstRequest = () => resolve({ ok: true, json: async () => ({}) });
    });
  };
  const params = {
    apiBaseUrl: 'https://api.example.test',
    userId: 'user-a',
    clientRecordId: 'rapid-record',
    foods: [detectedFood('快速點擊測試')],
    source: 'nutrition-label',
  };
  try {
    const first = saveRecord(params);
    const second = saveRecord(params);
    assert.equal(requestCount, 1);
    releaseFirstRequest();
    await Promise.all([first, second]);

    globalThis.fetch = async () => {
      requestCount += 1;
      return requestCount === 2
        ? { ok: false, json: async () => ({ error: 'temporary failure' }) }
        : { ok: true, json: async () => ({}) };
    };
    await assert.rejects(() => saveRecord({ ...params, clientRecordId: 'retry-record' }), /temporary failure/);
    await saveRecord({ ...params, clientRecordId: 'retry-record' });
    assert.equal(requestCount, 3);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('sends the meal type the record actually belongs to, not a fixed 點心', async () => {
  const originalFetch = globalThis.fetch;
  const captured = [];
  globalThis.fetch = async (_url, init) => {
    captured.push(JSON.parse(init.body));
    return { ok: true, json: async () => ({}) };
  };
  try {
    // 早餐時段掃描 → 早餐，而不是寫死的「點心」
    await saveRecord({
      apiBaseUrl: 'https://api.example.test',
      userId: 'user-a',
      clientRecordId: 'breakfast-record',
      foods: [detectedFood('燕麥粥')],
      source: 'camera',
      mealType: getAutoMealType(new Date('2026-09-10T08:30:00')),
    });
    assert.equal(captured[0].meal_type, '早餐');

    // 離線佇列晚上才補送早上那筆，餐別仍要跟著「當初入列的時間」
    await saveRecord({
      apiBaseUrl: 'https://api.example.test',
      userId: 'user-a',
      clientRecordId: 'replayed-breakfast',
      foods: [detectedFood('燕麥粥')],
      source: 'camera',
      mealType: getAutoMealType(new Date('2026-09-10T08:30:00')),
    });
    assert.equal(captured[1].meal_type, '早餐');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('splits the day into meals the same way the dashboard does', () => {
  assert.equal(getAutoMealType(new Date('2026-09-10T08:30:00')), '早餐');
  assert.equal(getAutoMealType(new Date('2026-09-10T12:15:00')), '午餐');
  assert.equal(getAutoMealType(new Date('2026-09-10T15:40:00')), '點心');
  assert.equal(getAutoMealType(new Date('2026-09-10T19:05:00')), '晚餐');
  assert.equal(normalizeMealType('午餐'), '午餐');
  assert.equal(normalizeMealType('brunch'), '點心');
});

test('per-meal budget follows the users disease-adjusted daily sodium limit', () => {
  // 一般人每日 2000mg → 單餐 ~667mg；腎臟病每日 1500mg → 單餐 500mg。
  // 寫死 800mg 會讓腎臟病患者的 700mg 餐點顯示成正常。
  assert.equal(Math.round(perMealBudget(2000, 2000)), 667);
  assert.equal(perMealBudget(1500, 2000), 500);
  assert.equal(Math.round(perMealBudget(undefined, 2000)), 667);
  assert.equal(Math.round(perMealBudget(0, 2000)), 667);
});
