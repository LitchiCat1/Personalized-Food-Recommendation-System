import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildOCRDetectedFood,
  describeScannerPendingNutrition,
  formatScannerNutritionSummary,
  formatScannerResultTitle,
  formatScannerSourceBadge,
  FOOD_NAME_REQUIRED_MESSAGE,
  hasReviewableNutritionMiss,
  hasUserConfirmableIdentity,
  manualSearchFood,
  normalizeFoodName,
  runNutritionLabelOCR,
  runPrediction,
  mergeNutritionEnrichmentResult,
  saveRecord,
} from '../lib/scanner.ts';
import { getAutoMealType, normalizeMealType, perMealBudget } from '../lib/meal.ts';

test('scanner summary distinguishes matched nutrition from pending foods', () => {
  assert.equal(formatScannerResultTitle(2, 5), '已配對 2 項營養資料');
  assert.equal(formatScannerResultTitle(0, 5), '5 項未計入營養合計');
  assert.equal(formatScannerResultTitle(0, 0), null);
});

test('scanner source badge reflects matched nutrient sources without guessing the model', () => {
  assert.equal(formatScannerSourceBadge(['TFDA', 'USDA FNDDS', 'TFDA']), 'TFDA + USDA');
  assert.equal(formatScannerSourceBadge(['custom-food']), '自訂');
  assert.equal(formatScannerSourceBadge([], 5), '尚未計入營養');
  assert.equal(formatScannerSourceBadge([]), '資料來源');
});

function pendingNutritionFixture() {
  return [
    [
      { item_id: 'apple-1', label: '蘋果', confidence: 0.95, reason: 'missing',
        recognition_status: 'recognized', nutrition_status: 'unmatched', search_hints: ['蘋果'] },
      { item_id: 'apple-2', label: '蘋果', confidence: 0.3, reason: 'low-confidence' },
    ],
    { selection: { items: [{ item_id: 'apple-1', reason: 'reviewed_match', weight_g: 150 }] },
      snapshot: { scan_id: 'scan-1', scan_revision: 0, snapshot_digest: 'digest-1', snapshot: { items: [
        { item_id: 'apple-1', candidates: [{ fdcId: '171688' }] },
      ] } } },
  ];
}

test('reviewed source availability changes only its pending row and does not count estimated nutrition', () => {
  const [items, snapshot] = pendingNutritionFixture();
  assert.equal(describeScannerPendingNutrition(items, null, null, true, true).items, items);
  const state = describeScannerPendingNutrition(items, snapshot, null, true, true);
  const result = state.items;
  assert.equal(state.reviewCount, 1);
  assert.match(result[0].reason, /已找到相容/);
  assert.match(result[0].reason, /未計入/);
  assert.equal(result[0].label, items[0].label);
  assert.equal(result[0].confidence, items[0].confidence);
  assert.deepEqual(result[0].search_hints, []);
  assert.equal(items[0].reason, 'missing');
  assert.equal(result[1], items[1]);
  assert.equal(formatScannerNutritionSummary(0, 0, 0, state), '尚無已計入的營養。1 項參考來源待確認、1 項未納入。');
});

test('confirmed reference is preview-only; stale or unavailable review actions do not count', () => {
  const [items, snapshot] = pendingNutritionFixture();
  const confirmation = { scan_id: 'scan-1', scan_revision: 0, snapshot_digest: 'digest-1', items: [
    { item_id: 'apple-1', status: 'confirmed_pending_revision' },
  ] };
  const state = describeScannerPendingNutrition(items, snapshot, confirmation, true, true);
  assert.match(state.items[0].reason, /僅供預覽/);
  assert.equal(formatScannerNutritionSummary(1, 110, 2, state),
    '已配對項目合計 110 kcal，鈉 2mg。另有 1 項營養僅供預覽、1 項未納入。');
  for (const key of ['scan_id', 'scan_revision', 'snapshot_digest']) {
    const stale = describeScannerPendingNutrition(items, snapshot, { ...confirmation, [key]: 'stale' }, true, true);
    assert.equal(stale.reviewCount, 1);
    assert.equal(stale.previewCount, 0);
  }
  assert.doesNotMatch(describeScannerPendingNutrition(items, snapshot, confirmation, true, false).items[0].reason, /預覽/);
  assert.doesNotMatch(describeScannerPendingNutrition(items, snapshot, null, false, false).items[0].reason, /待確認/);
});

test('raw candidates, reviewed no-match, deferred, and rejected have distinct wording', () => {
  const [items, snapshot] = pendingNutritionFixture();
  const raw = describeScannerPendingNutrition(items, { ...snapshot, selection: undefined }, null, true, true);
  assert.match(raw.items[0].reason, /候選/);
  assert.doesNotMatch(raw.items[0].reason, /相容/);
  snapshot.selection.items[0].reason = 'no_reviewed_source';
  snapshot.snapshot.snapshot.items[0].candidates = [];
  const miss = describeScannerPendingNutrition(items, snapshot, null, true, true);
  assert.match(miss.items[0].reason, /未找到相容的已審查營養來源/);
  assert.equal(miss.reviewCount, 0);
  for (const [status, expected] of [['confirmation_required', /保留待處理/], ['rejected', /不相符/]]) {
    const state = describeScannerPendingNutrition(items, snapshot, {
      scan_id: 'scan-1', scan_revision: 0, snapshot_digest: 'digest-1', items: [{ item_id: 'apple-1', status }],
    }, true, true);
    assert.match(state.items[0].reason, expected);
    assert.equal(state.reviewCount + state.previewCount, 0);
  }
});

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

test('vision mapping preserves missing nutrient flags for honest display', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({ detections: [{
      name_zh: '滷肉', confidence: 0.95, estimated_weight_g: 80,
      nutrition: detectedFood().nutrition, source: 'USDA FNDDS',
      missing_nutrition_fields: ['trans_fat'],
    }] }),
  });
  try {
    const result = await runPrediction({
      apiBaseUrl: 'http://localhost:5000', imageBase64: 'dGVzdA==', healthConditions: [], allergens: [],
    });
    assert.deepEqual(result.detections[0].missingNutritionFields, ['trans_fat']);
    assert.equal(result.detections[0].foodName, '滷肉');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('vision mapping preserves server item IDs and persisted scan context', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({
      detections: [{
        item_id: 'scan-42:0', name_zh: '糯米腸', confidence: 0.95, estimated_weight_g: 120,
        nutrition: detectedFood().nutrition, source: 'TFDA',
      }],
      scan_context: {
        status: 'persisted', scan_id: 'scan-42', scan_revision: 0,
        authority_token: 'authority-token', items: [{
          item_id: 'scan-42:0', item_revision: 0, name_zh: '糯米腸', confidence: 0.95,
          weight_confidence: 0.8, estimated_weight_g: 120, food_state: 'prepared',
          identity_confirmation_required: false,
          preparation_method: null, components_scope: 'food_only', brand: null, variant: null,
          validation_issues: [],
        }],
      },
    }),
  });
  try {
    const result = await runPrediction({
      apiBaseUrl: 'http://localhost:5000', imageBase64: 'dGVzdA==', healthConditions: [], allergens: [],
    });
    assert.equal(result.detections[0].id, 'scan-42:0');
    assert.equal(result.scanContext.scan_id, 'scan-42');
    assert.equal(result.scanContext.items[0].item_id, 'scan-42:0');
    assert.equal(result.scanContext.authority_token, 'authority-token');
    assert.equal(result.scanContext.items[0].identity_confirmation_required, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('a high-confidence local nutrition miss can continue to FDC candidate review', () => {
  const context = {
    status: 'persisted', scan_id: 'scan-miss', scan_revision: 0,
    items: [{ item_id: 'scan-miss:0', validation_issues: [] }],
  };
  assert.equal(hasReviewableNutritionMiss([{
    item_id: 'scan-miss:0', label: '蘋果', confidence: 0.95, reason: 'no local nutrition',
    recognition_status: 'recognized', nutrition_status: 'unmatched',
  }], context), true);
});

test('a rejected scan item can be name-confirmed only with complete server context', () => {
  const context = {
    status: 'persisted', scan_id: 'scan-identity', scan_revision: 0,
    items: [{ item_id: 'scan-identity:0', item_revision: 0, name_zh: '炒菜葉',
      identity_confirmation_required: true, validation_issues: [], food_state: 'prepared',
      preparation_method: 'stir_fried', components_scope: 'food_only' }],
  };
  const rejected = [{ item_id: 'scan-identity:0', label: '炒菜葉', confidence: 0.4, reason: 'needs confirmation' }];
  assert.equal(hasUserConfirmableIdentity(rejected, context), true);
  assert.equal(hasUserConfirmableIdentity(rejected, {
    ...context, items: [{ ...context.items[0], preparation_method: 'unknown' }],
  }), false);
  assert.equal(hasUserConfirmableIdentity(rejected, {
    ...context, items: [{ ...context.items[0], validation_issues: ['invalid_state'] }],
  }), false);
  assert.equal(hasUserConfirmableIdentity([], context), false);
});

test('FDC candidate review stays closed for low-confidence or invalid recognition', () => {
  const context = {
    status: 'persisted', scan_id: 'scan-miss', scan_revision: 0,
    items: [{ item_id: 'scan-miss:0', validation_issues: [] }],
  };
  assert.equal(hasReviewableNutritionMiss([{
    item_id: 'scan-miss:0', label: '不明食物', confidence: 0.3, reason: 'low confidence',
  }], context), false);
  assert.equal(hasReviewableNutritionMiss([{
    item_id: 'scan-miss:0', label: '蘋果', confidence: 0.95, reason: 'invalid recognition',
    recognition_status: 'recognized', nutrition_status: 'unmatched',
  }], { ...context, items: [{ item_id: 'scan-miss:0', validation_issues: ['missing_food_state'] }] }), false);
  assert.equal(hasReviewableNutritionMiss([{
    item_id: 'scan-miss:other', label: '蘋果', confidence: 0.95, reason: 'wrong scan item',
    recognition_status: 'recognized', nutrition_status: 'unmatched',
  }], context), false);
});

test('stale vision 401 does not dispatch logout for a newer session', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const events = [];
  globalThis.window = { dispatchEvent: (event) => events.push(event.type) };
  globalThis.fetch = async () => ({
    ok: false,
    status: 401,
    json: async () => ({ error: 'expired token' }),
  });
  try {
    const request = {
      apiBaseUrl: 'https://example.test', imageBase64: 'dGVzdA==',
      healthConditions: [], allergens: [], auth: { accessToken: 'old-token' },
    };
    await assert.rejects(runPrediction({ ...request, isCurrentSession: () => false }));
    assert.deepEqual(events, []);
    await assert.rejects(runPrediction({ ...request, isCurrentSession: () => true }));
    assert.deepEqual(events, ['nutrilens:unauthorized']);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('enrichment merge adds only complete point-value portions', () => {
  const base = detectedFood('原始辨識');
  const response = {
    result: { items: [{
      item_id: 'scan-1:0', item_revision: 0, original_visual_name: '糯米腸',
      status: 'accepted', origin: 'web',
      recognition_context: { name_zh: '糯米腸', confidence: 0.9, estimated_weight_g: 120 },
      nutrition_profile: { source_details: { source_id: 'reviewed-source' } },
      portion: {
        weight_g: 120, values: { calories: 240, protein: 8, carbs: 32, fat: 9, sodium: 360, fiber: null,
          sugar: null, saturated_fat: null, trans_fat: null },
        missing_nutrition_fields: ['fiber', 'sugar', 'saturated_fat', 'trans_fat'],
      },
    }] },
  };
  const merged = mergeNutritionEnrichmentResult([{ ...base, id: 'scan-1:0' }], response);
  assert.equal(merged.length, 1);
  assert.equal(merged[0].nutrition.calories, 240);
  assert.equal(merged[0].source, 'web:reviewed-source');
  assert.deepEqual(merged[0].missingNutritionFields, ['fiber', 'sugar', 'saturated_fat', 'trans_fat']);
  const unresolved = mergeNutritionEnrichmentResult([base], {
    result: { items: [{ item_id: 'ocr-test', portion: { values: { calories: null } } }] },
  });
  assert.equal(unresolved[0].nutrition.calories, 180);
});

test('enrichment with unknown weight stays unresolved and never assumes 100g', () => {
  const item = {
    item_id: 'scan-unknown:0', item_revision: 0, original_visual_name: '未知重量食品',
    status: 'accepted', origin: 'web',
    recognition_context: { name_zh: '未知重量食品', confidence: 0.9 },
    nutrition_profile: { source_details: { source_id: 'reviewed-source' } },
    portion: {
      values: { calories: 240, protein: 8, carbs: 32, fat: 9, sodium: 360, fiber: 2,
        sugar: 1, saturated_fat: 3, trans_fat: 0 },
      missing_nutrition_fields: [],
    },
  };
  const response = { result: { items: [item] } };
  const added = mergeNutritionEnrichmentResult([], response);
  assert.deepEqual(added, []);

  const original = { ...detectedFood('原始辨識'), id: item.item_id };
  const retained = mergeNutritionEnrichmentResult([original], response);
  assert.deepEqual(retained, [original]);

  const invalidPortion = mergeNutritionEnrichmentResult([], {
    result: { items: [{ ...item, item_id: 'scan-invalid:0', recognition_context: {
      name_zh: '無效重量食品', confidence: 0.9, estimated_weight_g: 120,
    }, portion: { ...item.portion, weight_g: 0 } }] },
  });
  assert.deepEqual(invalidPortion, []);
});

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

test('a replayed record carries the time it was queued; a live save lets the backend stamp it', async () => {
  const originalFetch = globalThis.fetch;
  const captured = [];
  globalThis.fetch = async (_url, init) => {
    captured.push(JSON.parse(init.body));
    return { ok: true, json: async () => ({}) };
  };
  const base = {
    apiBaseUrl: 'https://api.example.test',
    userId: 'user-a',
    foods: [detectedFood('滷肉飯')],
    source: 'camera',
    mealType: '晚餐',
  };
  try {
    await saveRecord({ ...base, clientRecordId: 'live-record' });
    assert.equal('timestamp' in captured[0], false);

    // 23:50 排隊的晚餐隔天早上才補送，要存成當晚，不是隔天早上
    await saveRecord({ ...base, clientRecordId: 'queued-record', timestamp: '2026-10-25T23:50:00.000+08:00' });
    assert.equal(captured[1].timestamp, '2026-10-25T23:50:00.000+08:00');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('a non-JSON error page becomes a readable message instead of a parse error', async () => {
  // 後端逾時或 502 時回的是 HTML，直接 resp.json() 會丟出 "Unexpected token '<'"
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false,
    status: 502,
    json: async () => { throw new SyntaxError("Unexpected token '<', \"<!doctype \"... is not valid JSON"); },
  });
  const image = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
  try {
    await assert.rejects(
      () => runPrediction({ apiBaseUrl: 'https://api.example.test', imageBase64: image, healthConditions: [], allergens: [] }),
      (error) => !/Unexpected token/.test(error.message) && /HTTP 502/.test(error.message),
    );
    await assert.rejects(
      () => manualSearchFood({ apiBaseUrl: 'https://api.example.test', keyword: '白飯' }),
      (error) => !/Unexpected token/.test(error.message) && /HTTP 502/.test(error.message),
    );
    await assert.rejects(
      () => runNutritionLabelOCR({ apiBaseUrl: 'https://api.example.test', imageBase64: image }),
      (error) => !/Unexpected token/.test(error.message),
    );
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
