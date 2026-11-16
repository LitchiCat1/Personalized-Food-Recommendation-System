import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const filename = fileURLToPath(new URL('../store/useStore.ts', import.meta.url));
const module = { exports: {} };
const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const defaults = {
  gender: 'female', height: 165, weight: 60, age: 30,
  activityLevel: 'moderate', activityMultiplier: 1.55, targetWeight: 0,
  dietType: 'omnivore', healthConditions: [], allergens: [],
};
const emptyNutrition = {
  calories: { current: 0, target: 0 }, protein: { current: 0, target: 0 },
  carbs: { current: 0, target: 0 }, sugar: { current: 0, target: 0 },
  fat: { current: 0, target: 0 }, saturated_fat: { current: 0, target: 0 },
  trans_fat: { current: 0, target: 0 }, sodium: { current: 0, target: 0 },
  fiber: { current: 0, target: 0 },
};
new Function('require', 'module', 'exports', code)((id) => {
  if (id === 'zustand') return require('zustand');
  if (id === '@/lib/meal') return { MEALS_PER_DAY: 3, getAutoMealType() {}, normalizeMealType(value) { return value; } };
  if (id === '@/lib/safety-selection') return { toggleSelection(values) { return values; } };
  if (id === '@/constants/nutrition-display') return { EMPTY_DAILY_NUTRITION: emptyNutrition };
  if (id === '@/constants/profile-defaults') return { NEW_USER_PROFILE: defaults };
  if (id === '@/lib/network') return { resolveApiBaseUrl: () => 'https://api.one.test' };
  throw new Error(`Unexpected runtime dependency: ${id}`);
}, module, module.exports);
const { useStore } = module.exports;

const food = {
  id: 'scan-1:0', foodName: '糯米腸', confidence: 85, estimatedWeight: 120,
  nutrition: { calories: 250, protein: 8, carbs: 30, fat: 9, sodium: 500, fiber: 1 },
};
const reference = (scanId, ownerUserId = 'user-1', apiBaseUrl = 'https://api.one.test') => ({
  ownerUserId, apiBaseUrl, scan_id: scanId, scan_revision: 0,
});
const candidateSnapshot = (scanId) => ({
  status: 'available', snapshot: { scan_id: scanId, scan_revision: 0 },
});

test('new scan, clear, and background scan start invalidate candidate references', () => {
  const first = reference('scan-1');
  useStore.getState().setAuthSession({ userId: 'user-1', accessToken: 'token-1' });
  useStore.getState().setScanResult([food], first);
  useStore.getState().setFdcCandidateSnapshot(first, candidateSnapshot('scan-1'));
  assert.equal(useStore.getState().scanResult.fdcCandidateSnapshot.snapshot.scan_id, 'scan-1');

  const second = reference('scan-2');
  useStore.getState().setScanResult([food], second);
  assert.equal(useStore.getState().scanResult.fdcCandidateSnapshot, null);
  useStore.getState().setFdcCandidateSnapshot(first, candidateSnapshot('scan-1'));
  assert.equal(useStore.getState().scanResult.fdcCandidateSnapshot, null);

  useStore.getState().setFdcCandidateSnapshot(second, candidateSnapshot('scan-2'));
  useStore.getState().setScanning(true);
  assert.equal(useStore.getState().scanResult.serverScanReference, null);
  assert.equal(useStore.getState().scanResult.fdcCandidateSnapshot, null);

  useStore.getState().setScanResult([food], second);
  useStore.getState().clearScan();
  assert.equal(useStore.getState().scanResult.serverScanReference, null);
  assert.equal(useStore.getState().scanResult.fdcCandidateSnapshot, null);
});

test('logout, account switch, and backend change clear scan references', () => {
  useStore.getState().setAuthSession({ userId: 'user-1', accessToken: 'token-1' });
  const first = reference('scan-3');
  useStore.getState().setScanResult([food], first);
  useStore.getState().setFdcCandidateSnapshot(first, candidateSnapshot('scan-3'));
  useStore.getState().setAuthSession({ userId: 'user-2', accessToken: 'token-2' });
  assert.equal(useStore.getState().scanResult.serverScanReference, null);
  assert.equal(useStore.getState().scanResult.fdcCandidateSnapshot, null);

  const second = reference('scan-4', 'user-2');
  useStore.getState().setScanResult([food], second);
  useStore.getState().setFdcCandidateSnapshot(second, candidateSnapshot('scan-4'));
  useStore.getState().setApiBaseUrl('https://api.two.test');
  assert.equal(useStore.getState().scanResult.detections.length, 0);
  assert.equal(useStore.getState().scanResult.serverScanReference, null);
  assert.equal(useStore.getState().scanResult.fdcCandidateSnapshot, null);

  useStore.getState().setAuthSession(null);
  assert.equal(useStore.getState().scanResult.serverScanReference, null);
});

test('issued confirmation revision advances only its current scan and clears old candidates', () => {
  useStore.getState().setAuthSession({ userId: 'user-1', accessToken: 'token-1' });
  useStore.getState().setApiBaseUrl('https://api.one.test');
  const first = reference('scan-revision');
  useStore.getState().setScanResult([food], first);
  useStore.getState().setFdcCandidateSnapshot(first, candidateSnapshot('scan-revision'));
  assert.deepEqual(useStore.getState().scanResult.serverScanReference, first);
  assert.equal(useStore.getState().user.userId, first.ownerUserId);
  assert.equal(useStore.getState().apiBaseUrl, first.apiBaseUrl);

  useStore.getState().advanceFdcCandidateScanRevision(first, 1);
  assert.equal(useStore.getState().scanResult.serverScanReference.scan_revision, 1);
  assert.equal(useStore.getState().scanResult.fdcCandidateSnapshot, null);
  assert.equal(useStore.getState().scanResult.detections[0].confidence, food.confidence);

  useStore.getState().advanceFdcCandidateScanRevision(first, 2);
  assert.equal(useStore.getState().scanResult.serverScanReference.scan_revision, 1);
  const stale = { ...first, scan_id: 'stale-scan' };
  useStore.getState().advanceFdcCandidateScanRevision(stale, 1);
  assert.equal(useStore.getState().scanResult.serverScanReference.scan_id, 'scan-revision');
});

test('terminal expiry clears only the matching reference and retains recognized nutrition', () => {
  useStore.getState().setAuthSession({ userId: 'user-1', accessToken: 'token-1' });
  useStore.getState().setApiBaseUrl('https://api.one.test');
  const first = reference('expired-scan');
  useStore.getState().setScanResult([food], first);
  useStore.getState().setFdcCandidateSnapshot(first, candidateSnapshot('expired-scan'));
  const before = useStore.getState().scanResult;
  for (const stale of [reference('old-scan'), { ...first, scan_revision: 1 },
    reference('expired-scan', 'other-user'), reference('expired-scan', 'user-1', 'https://api.two.test')]) {
    useStore.getState().invalidateFdcScanReference(stale);
    assert.equal(useStore.getState().scanResult, before);
  }
  useStore.getState().invalidateFdcScanReference(first);
  const result = useStore.getState().scanResult;
  assert.equal(result.serverScanReference, null);
  assert.equal(result.fdcCandidateSnapshot, null);
  assert.equal(result.detections, before.detections);
  assert.equal(result.timestamp, before.timestamp);
  useStore.getState().invalidateFdcScanReference(first);
  assert.equal(useStore.getState().scanResult, result);
  const next = reference('new-scan');
  useStore.getState().setScanResult([food], next);
  useStore.getState().invalidateFdcScanReference(first);
  useStore.getState().setFdcCandidateSnapshot(first, candidateSnapshot('expired-scan'));
  assert.equal(useStore.getState().scanResult.serverScanReference, next);
  assert.equal(useStore.getState().scanResult.fdcCandidateSnapshot, null);
});
