import type { ApiAuth, RecordsQueryOptions } from './api';
import type {
  NutritionHistoryResponseV2, NutritionRecordCreateV2,
  NutritionRecordPatchV2, NutritionRecordPreviewV2, NutritionRecordsResponseV2,
} from './nutrition-contract';
import { assertNutritionHistoryResponse } from './nutrition-read-history';
import {
  NutritionApiError, assertNutritionCanonicalV2 as checkCanonical,
  assertNutritionSavedRecordV2 as checkSaved,
  assertVersionedNutritionRecord as checkRecord,
} from './nutrition-response-validation';

export { NutritionApiError } from './nutrition-response-validation';

function incompatible(): never {
  throw new NutritionApiError('後端回傳的營養資料格式不相容', 200, 'invalid_response');
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function number(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

function integer(value: unknown): value is number {
  return number(value) && Number.isSafeInteger(value);
}

function serialize(payload: NutritionRecordPreviewV2 | NutritionRecordPatchV2): string {
  if (payload.nutrition_contract_version !== 2 || !Array.isArray(payload.foods) || payload.foods.length === 0 ||
      payload.foods.some((food) => 'nutrition_profile' in food || 'source' in food) ||
      ('base_revision' in payload && !integer(payload.base_revision))) {
    throw new NutritionApiError('新版紀錄請求格式不正確', 0, 'invalid_request');
  }
  try {
    return JSON.stringify(payload, (_key, value) => {
      if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('nonfinite');
      return value;
    });
  } catch {
    throw new NutritionApiError('紀錄含無法儲存的數值', 0, 'invalid_request');
  }
}

async function request(
  apiBaseUrl: string, path: string, method: string, auth?: ApiAuth,
  payload?: NutritionRecordPreviewV2 | NutritionRecordPatchV2,
): Promise<Record<string, unknown>> {
  const body = payload ? serialize(payload) : undefined;
  const headers: Record<string, string> = { 'X-Nutrition-Contract-Version': '2' };
  if (body) headers['Content-Type'] = 'application/json';
  if (auth?.accessToken) headers.Authorization = `Bearer ${auth.accessToken}`;
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl.replace(/\/$/, '')}${path}`, { method, headers, body });
  } catch {
    throw new NutritionApiError('無法連線到後端，請稍後重試', 0, 'network_error');
  }
  if (response.status === 401 && typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(new Event('nutrilens:unauthorized'));
  }
  let data: unknown;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) {
    const error = object(data) ? data : {};
    throw new NutritionApiError(
      typeof error.error === 'string' ? error.error : `營養紀錄服務錯誤（HTTP ${response.status}）`,
      response.status, typeof error.error_code === 'string' ? error.error_code : 'http_error',
      integer(error.required_nutrition_contract_version) ? error.required_nutrition_contract_version : null,
    );
  }
  if (!object(data)) incompatible();
  return data;
}

export async function previewNutritionRecordV2(apiBaseUrl: string, payload: NutritionRecordPreviewV2, auth?: ApiAuth) {
  const result = await request(apiBaseUrl, '/record/preview', 'POST', auth, payload);
  checkCanonical(result.record);
  return { record: result.record };
}

export async function createNutritionRecordV2(apiBaseUrl: string, payload: NutritionRecordCreateV2, auth?: ApiAuth) {
  const result = await request(apiBaseUrl, '/record', 'POST', auth, payload);
  // An idempotent POST may return a pre-existing v1 record. Never relabel it v2.
  checkRecord(result.record);
  if (typeof result.deduplicated !== 'boolean' || typeof result.message !== 'string' ||
      (result.record.nutrition_contract_version !== 2 && !result.deduplicated)) incompatible();
  return { record: result.record, deduplicated: result.deduplicated, message: result.message };
}

export async function updateNutritionRecordV2(
  apiBaseUrl: string, userId: string, clientRecordId: string, payload: NutritionRecordPatchV2, auth?: ApiAuth,
) {
  const result = await request(apiBaseUrl, recordPath(userId, clientRecordId), 'PATCH', auth, payload);
  checkSaved(result.record);
  if (typeof result.message !== 'string') incompatible();
  return { record: result.record, message: result.message };
}

function recordPath(userId: string, clientRecordId?: string): string {
  return `/records/${encodeURIComponent(userId)}${clientRecordId === undefined ? '' : `/${encodeURIComponent(clientRecordId)}`}`;
}

export async function deleteNutritionRecordV2(apiBaseUrl: string, userId: string, clientRecordId: string, auth?: ApiAuth) {
  const result = await request(apiBaseUrl, recordPath(userId, clientRecordId), 'DELETE', auth);
  checkRecord(result.record);
  if (typeof result.message !== 'string') incompatible();
  return { record: result.record, message: result.message };
}

export async function fetchNutritionRecordsV2(
  apiBaseUrl: string, userId: string, date?: string, auth?: ApiAuth, options?: RecordsQueryOptions,
): Promise<NutritionRecordsResponseV2> {
  const query = new URLSearchParams();
  if (date) query.set('date', date);
  for (const key of ['limit', 'offset'] as const) {
    if (options?.[key] !== undefined) query.set(key, String(options[key]));
  }
  const result = await request(apiBaseUrl, `${recordPath(userId)}${query.size ? `?${query}` : ''}`, 'GET', auth);
  if (!Array.isArray(result.records) || result.count !== result.records.length) incompatible();
  result.records.forEach(checkRecord);
  if (result.records.some((record) => record.user_id !== userId || (date && !record.timestamp.startsWith(date)))) incompatible();
  return result as NutritionRecordsResponseV2;
}

export async function fetchNutritionHistoryV2(
  apiBaseUrl: string, userId: string, days = 7, auth?: ApiAuth,
): Promise<NutritionHistoryResponseV2> {
  const result = await request(apiBaseUrl, `/history/${encodeURIComponent(userId)}?days=${days}`, 'GET', auth);
  try { assertNutritionHistoryResponse(result); } catch { incompatible(); }
  if (result.user_id !== userId || result.days !== Math.min(365, Math.max(1, days))) incompatible();
  return result;
}
