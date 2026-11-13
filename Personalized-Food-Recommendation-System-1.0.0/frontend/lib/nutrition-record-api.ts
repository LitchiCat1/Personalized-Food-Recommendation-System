import type { ApiAuth, RecordsQueryOptions } from './api';
import type {
  NutritionHistoryResponseV2, NutritionRecordCanonicalV2, NutritionRecordCreateV2,
  NutritionRecordPatchV2, NutritionRecordPreviewV2, NutritionRecordsResponseV2,
  NutritionRecordV2, VersionedNutritionRecord,
} from './nutrition-contract';
import { aggregateNutritionCoverage, calculateNutritionPortion, NUTRIENT_KEYS } from './nutrition-calculation';

export class NutritionApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requiredNutritionContractVersion: number | null;

  constructor(message: string, status: number, code: string, requiredVersion: number | null = null) {
    super(message);
    this.name = 'NutritionApiError';
    this.status = status;
    this.code = code;
    this.requiredNutritionContractVersion = requiredVersion;
  }
}

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

function values(value: unknown): boolean {
  return object(value) && NUTRIENT_KEYS.every((key) => value[key] === null || number(value[key]));
}

function sameNumber(left: unknown, right: number | null): boolean {
  if (right === null) return left === null;
  return number(left) && (left === right || Math.abs(left - right) <= Math.max(left, right) * Number.EPSILON * 8);
}

function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function sameList(left: unknown, right: string[]): boolean {
  return strings(left) && left.length === right.length && left.every((item, index) => item === right[index]);
}

function checkCoverage(value: unknown): void {
  if (!object(value) || value.schema_version !== 'NutritionCoverageV1' || !object(value.nutrients)) incompatible();
  for (const key of NUTRIENT_KEYS) {
    const row = value.nutrients[key];
    if (!object(row) || !number(row.known_sum) || !number(row.known_bounds_sum) ||
        !['known_items', 'eligible_items', 'unresolved_items', 'bounded_items'].every((name) => integer(row[name])) ||
        (row.legacy_items !== undefined && !integer(row.legacy_items)) ||
        !['complete', 'partial', 'unknown', 'legacy_unknown'].includes(String(row.status)) ||
        !(row.total_upper_bound === null || number(row.total_upper_bound)) ||
        row.upper_bound_comparison !== (row.total_upper_bound === null ? null : 'less_than')) incompatible();
    if ((row.known_items as number) + (row.unresolved_items as number) !== row.eligible_items ||
        (row.bounded_items as number) + ((row.legacy_items as number | undefined) ?? 0) > (row.unresolved_items as number)) incompatible();
    const hasLegacy = typeof row.legacy_items === 'number' && row.legacy_items > 0;
    const status = hasLegacy ? 'legacy_unknown' : row.eligible_items !== 0 && row.known_items === row.eligible_items
      ? 'complete' : row.known_items || row.bounded_items ? 'partial' : 'unknown';
    const hasBound = !hasLegacy && (row.bounded_items as number) > 0 &&
      (row.known_items as number) + (row.bounded_items as number) === row.eligible_items;
    const upper = hasBound ? (row.known_sum as number) + (row.known_bounds_sum as number) : null;
    if (row.status !== status || !sameNumber(row.total_upper_bound, upper) ||
        (!row.bounded_items && row.known_bounds_sum !== 0)) incompatible();
  }
}

function checkCanonical(value: unknown): asserts value is NutritionRecordCanonicalV2 {
  if (!object(value) || value.nutrition_contract_version !== 2 || !Array.isArray(value.foods) ||
      value.foods.length === 0 || value.foods.length > 200 || typeof value.contains_fried_food !== 'boolean' ||
      !object(value.nutrition_context)) incompatible();
  const context = value.nutrition_context;
  if (context.contract_version !== 2 || !integer(context.revision) ||
      context.visual_completeness !== 'not_verified' ||
      context.recognition_context_authority !== 'client_supplied' ||
      !strings(context.unresolved_item_ids)) incompatible();
  checkCoverage(context.coverage);
  const seen = new Set<string>();
  for (const food of value.foods) {
    if (!object(food) || typeof food.item_id !== 'string' || !food.item_id || seen.has(food.item_id) ||
        typeof food.name !== 'string' || !food.name || typeof food.included !== 'boolean' ||
        (food.included === false && food.exclusion_reason !== 'not_consumed') ||
        !(food.weight_g === null || (number(food.weight_g) && food.weight_g > 0)) ||
        !['unknown', 'vision_estimate', 'user_adjusted', 'user_weighed', 'label_weight', 'assumed'].includes(String(food.portion_source)) ||
        typeof food.source !== 'string' || typeof food.is_fried !== 'boolean' || !strings(food.allergens) ||
        !(food.gi === null || typeof food.gi === 'string') || !strings(food.missing_nutrition_fields) ||
        !values(food) || !object(food.nutrition_intake) ||
        !values(food.nutrition_intake.values) || !values(food.nutrition_intake.upper_bounds) ||
        food.nutrition_intake.bound_comparison !== 'less_than' ||
        food.nutrition_intake.weight_g !== food.weight_g || food.nutrition_intake.portion_source !== food.portion_source ||
        !(food.nutrition_profile === null ||
          (object(food.nutrition_profile) && food.nutrition_profile.schema_version === 'NutritionProfileV1' &&
           object(food.nutrition_profile.source_basis) && object(food.nutrition_profile.source_nutrients)))) incompatible();
    seen.add(food.item_id);
  }
  // Check the transport snapshot against its original cells. The server still
  // owns source authentication, full profile validation, and medical decisions.
  try {
    const snapshot = value as unknown as NutritionRecordCanonicalV2;
    const expected = aggregateNutritionCoverage(snapshot.foods.map((food) => ({ ...food, profile: food.nutrition_profile })));
    for (const food of snapshot.foods) {
      const portion = calculateNutritionPortion(food.nutrition_profile, food.weight_g, food.portion_source);
      for (const key of NUTRIENT_KEYS) {
        if (!sameNumber(food[key], portion.values[key]) || !sameNumber(food.nutrition_intake.values[key], portion.values[key]) ||
            !sameNumber(food.nutrition_intake.upper_bounds[key], portion.upper_bounds[key])) incompatible();
      }
      if (!sameList(food.missing_nutrition_fields, portion.missing_nutrition_fields) ||
          !sameList(food.nutrition_intake.missing_nutrition_fields, portion.missing_nutrition_fields)) incompatible();
    }
    const coverage = snapshot.nutrition_context.coverage;
    if (!sameList(coverage.included_item_ids, expected.included_item_ids ?? []) ||
        !sameList(coverage.excluded_item_ids, expected.excluded_item_ids ?? []) ||
        !sameList(context.unresolved_item_ids, snapshot.foods.filter((food) => food.included && food.missing_nutrition_fields.length > 0).map((food) => food.item_id))) incompatible();
    for (const key of NUTRIENT_KEYS) {
      const actual = coverage.nutrients[key];
      const row = expected.nutrients[key];
      if (actual.status !== row.status || actual.known_items !== row.known_items || actual.eligible_items !== row.eligible_items ||
          actual.bounded_items !== row.bounded_items || !sameNumber(actual.known_sum, row.known_sum) ||
          !sameNumber(actual.known_bounds_sum, row.known_bounds_sum) || !sameNumber(actual.total_upper_bound, row.total_upper_bound) ||
          !sameNumber(value[`total_${key}`], row.known_sum)) incompatible();
    }
  } catch { incompatible(); }
}

function checkSaved(value: unknown): asserts value is NutritionRecordV2 {
  checkCanonical(value);
  const record = value as unknown as Record<string, unknown>;
  if (typeof record.user_id !== 'string' || typeof record.client_record_id !== 'string' ||
      typeof record.timestamp !== 'string') incompatible();
}

function checkRecord(value: unknown): asserts value is VersionedNutritionRecord {
  if (!object(value)) incompatible();
  if (value.nutrition_contract_version === 2) checkSaved(value);
  else if ((value.nutrition_contract_version !== undefined && value.nutrition_contract_version !== 1) ||
           typeof value.user_id !== 'string' || typeof value.timestamp !== 'string') incompatible();
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
  return result as NutritionRecordsResponseV2;
}

export async function fetchNutritionHistoryV2(
  apiBaseUrl: string, userId: string, days = 7, auth?: ApiAuth,
): Promise<NutritionHistoryResponseV2> {
  const result = await request(apiBaseUrl, `/history/${encodeURIComponent(userId)}?days=${days}`, 'GET', auth);
  if (result.nutrition_contract_version !== 2 || typeof result.user_id !== 'string' ||
      !Array.isArray(result.daily) || !object(result.summary) ||
      result.summary.aggregation_scope !== 'recorded_days_in_requested_range' || !values(result.summary.avg_known_sum)) incompatible();
  checkCoverage(result.summary.nutrition_coverage);
  for (const day of result.daily) {
    if (!object(day) || typeof day.date !== 'string') incompatible();
    checkCoverage(day.nutrition_coverage);
  }
  return result as NutritionHistoryResponseV2;
}
