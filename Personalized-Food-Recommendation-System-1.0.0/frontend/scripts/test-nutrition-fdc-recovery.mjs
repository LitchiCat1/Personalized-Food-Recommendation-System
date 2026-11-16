import assert from 'node:assert/strict';
import test from 'node:test';
import { getNutritionFdcRecovery } from '../lib/nutrition-fdc-recovery.ts';

test('expired, stale, or withdrawn references require rescan instead of retry', () => {
  for (const code of ['expired', 'revoked', 'superseded', 'scan_not_found', 'scan_unavailable',
    'snapshot_unavailable', 'snapshot_mismatch', 'revision_conflict', 'authorization_changed',
    'preview_not_found', 'preview_unavailable']) {
    const result = getNutritionFdcRecovery({ code, status: 409, message: 'raw server message' });
    assert.equal(result.rescan, true, code);
    assert.equal(result.retryable, false, code);
    assert.match(result.message, /重新拍照/);
    assert.doesNotMatch(result.message, /raw server/);
  }
});

test('temporary network, rate, and upstream failures retain safe retry', () => {
  for (const failure of [{ code: 'network_error', status: 0 }, { code: 'busy', status: 429 },
    { code: 'reservation_lost', status: 409 }, { code: 'upstream_error', status: 502 },
    { code: 'timeout', status: 504 }]) {
    const result = getNutritionFdcRecovery(failure);
    assert.equal(result.rescan, false);
    assert.equal(result.retryable, true);
  }
});

test('disabled, unauthorized, malformed, and unknown errors do not retry automatically', () => {
  for (const failure of [null, {}, new Error('secret'), { code: 'feature_disabled', status: 503 },
    { status: 401 }, { status: 403 }, { code: 'invalid_response', status: 200 }]) {
    const result = getNutritionFdcRecovery(failure);
    assert.equal(result.rescan, false);
    assert.equal(result.retryable, false);
    assert.doesNotMatch(result.message, /secret/);
  }
});
