// Runs existing helpers and the transpiled store with a mocked network adapter.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { runPrediction, saveRecord } from '../frontend/lib/scanner.ts';
import { createRecordFoodDrafts } from '../frontend/lib/dietary-records.ts';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const nativeRequire = createRequire(path.join(root, 'frontend', 'package.json'));
const ts = nativeRequire('typescript');
const cache = new Map();
function loadTs(filename) {
  if (cache.has(filename)) return cache.get(filename).exports;
  const module = { exports: {} };
  cache.set(filename, module);
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const scopedRequire = (id) => {
    if (id === '@/lib/network') return { resolveApiBaseUrl: () => 'http://isolated.invalid' };
    if (id.startsWith('@/')) return loadTs(path.join(root, 'frontend', id.slice(2) + '.ts'));
    return nativeRequire(id);
  };
  new Function('require', 'module', 'exports', code)(scopedRequire, module, module.exports);
  return module.exports;
}

const nutrition = { calories: 100, protein: 10, carbs: 10, fat: 5, sodium: null,
  fiber: null, sugar: null, saturated_fat: null, trans_fat: null, is_fried: false };
const apiFood = { name_zh: '測試食品', confidence: 0.95, estimated_weight_g: 100,
  nutrition, source: 'web_reference', nutrition_source_url: 'https://example.invalid/source',
  nutrition_status: 'partial', missing_nutrition_fields: ['sodium', 'fiber', 'sugar'],
  warnings: ['test-only prior warning'], bounding_box: {} };
const originalFetch = globalThis.fetch;
let request;
let mapped;
try {
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ detections: [apiFood] }) });
  mapped = (await runPrediction({ apiBaseUrl: 'http://isolated.invalid', imageBase64: 'dGVzdA==',
    healthConditions: [], allergens: [] })).detections[0];
  globalThis.fetch = async (_url, init) => {
    request = JSON.parse(init.body);
    return { ok: true, json: async () => ({}) };
  };
  await saveRecord({ apiBaseUrl: 'http://isolated.invalid', userId: 'probe-only',
    clientRecordId: 'probe-only', foods: [mapped], source: 'camera', mealType: '午餐' });
} finally {
  globalThis.fetch = originalFetch;
}
const { useStore } = loadTs(path.join(root, 'frontend', 'store', 'useStore.ts'));
const measuredFood = { ...mapped, nutrition: { ...nutrition, sodium: 800, fiber: 1, sugar: 1 },
  originalNutrition: undefined, originalEstimatedWeight: undefined };
useStore.getState().setScanResult([measuredFood]);
useStore.getState().updateScanFoodWeight(measuredFood.id, 200);
const doubled = useStore.getState().scanResult.detections[0];
for (const grams of [120, 270, 85, 100]) useStore.getState().updateScanFoodWeight(measuredFood.id, grams);
const restored = useStore.getState().scanResult.detections[0];
const report = {
  mode: 'existing_frontend_helpers_with_mocked_fetch_and_network_adapter',
  mappedSourceUrl: mapped.nutrition_source_url ?? null,
  mappedStatus: mapped.nutrition_status ?? null,
  mappedMissingFields: mapped.missingNutritionFields,
  serializedFood: request.foods[0],
  serializedMissingFieldsPreserved: 'missing_nutrition_fields' in request.foods[0],
  serializedWeightPreserved: 'estimated_weight_g' in request.foods[0],
  editDraft: createRecordFoodDrafts({ foods: [{ name: '測試', ...nutrition }] })[0],
  weightEdit: { originalSodium: 800, doubledSodium: doubled.nutrition.sodium,
    warningsAfterDoubling: doubled.warnings, restoredSodium: restored.nutrition.sodium,
    cumulativeRoundingDriftObserved: restored.nutrition.sodium !== 800 },
};
const output = path.join(root, 'docs', 'food-nutrition-evaluation', '2026-11-13', 'frontend.json');
fs.writeFileSync(output, JSON.stringify(report, null, 2));
process.stdout.write(JSON.stringify(report) + '\n');
