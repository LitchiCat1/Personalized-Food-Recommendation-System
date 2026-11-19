import type { ApiAuth } from './api';

export type NutritionEnrichmentItem = {
  item_id: string;
  item_revision: number;
  name_zh: string;
  confidence: number | null;
  weight_confidence: number | null;
  estimated_weight_g: number | null;
  food_state: string | null;
  preparation_method: string | null;
  components_scope: string | null;
  brand: string | null;
  variant: string | null;
  validation_issues: string[];
  identity_confirmation_required?: boolean;
  identity_confirmation_source?: 'user';
  identity_confirmation_id?: string;
};

/** Server-owned context returned by the vision endpoint.
 *
 * The client may carry this context forward, but must never invent or edit
 * its item set.  The backend compares it with the persisted scan snapshot.
 */
export type NutritionScanContext = {
  status: 'persisted';
  scan_id: string;
  scan_revision: number;
  items: NutritionEnrichmentItem[];
  expires_at?: string | null;
  authority_token?: string;
};

export type NutritionEnrichmentRequest = {
  user_id: string;
  scan_id: string;
  scan_revision: number;
  items: NutritionEnrichmentItem[];
  idempotency_key: string;
  source_policy_id: string;
  source_policy_revision: number;
  profiles?: Array<{
    profile_id: string;
    profile_hash: string;
    source_id: string;
    profile_revision: number;
  }>;
  wait_timeout?: number;
  scan_authority_token?: string;
};

export type NutritionEnrichmentStatus =
  | 'accepted' | 'partial' | 'complete' | 'success' | 'pending'
  | 'timeout' | 'rate_limited' | 'upstream_error' | 'busy'
  | 'invalid_output' | 'source_conflict' | 'not_found';

export type NutritionEnrichmentResult = {
  schema_version: 'NutritionEnrichmentRouteV1';
  items: Array<Record<string, unknown>>;
  nutrition_coverage: Record<string, unknown>;
};

export type NutritionEnrichmentResponse = {
  status: NutritionEnrichmentStatus;
  request_id: string | null;
  replayed: boolean;
  result: NutritionEnrichmentResult | null;
  error: { code: string; message: string } | null;
};

export function buildNutritionEnrichmentRequest(params: {
  userId: string;
  context: NutritionScanContext;
  sourcePolicyId: string;
  sourcePolicyRevision: number;
  idempotencyKey?: string;
  waitTimeout?: number;
}): NutritionEnrichmentRequest {
  const { userId, context } = params;
  return {
    user_id: userId,
    scan_id: context.scan_id,
    scan_revision: context.scan_revision,
    items: context.items.map((item) => ({ ...item })),
    idempotency_key: params.idempotencyKey || `nutrition:${context.scan_id}:${context.scan_revision}`,
    source_policy_id: params.sourcePolicyId,
    source_policy_revision: params.sourcePolicyRevision,
    ...(params.waitTimeout === undefined ? {} : { wait_timeout: params.waitTimeout }),
    ...(context.authority_token ? { scan_authority_token: context.authority_token } : {}),
  };
}

export class NutritionEnrichmentApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfter: string | null;

  constructor(message: string, status: number, code: string, retryAfter: string | null = null) {
    super(message);
    this.name = 'NutritionEnrichmentApiError';
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function finiteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function text(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.trim() === value && !/[\u0000-\u001f\u007f]/.test(value);
}

function reportUnauthorized(response: Response): void {
  if (response.status === 401 && typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(new Event('nutrilens:unauthorized'));
  }
}

function validRequest(request: NutritionEnrichmentRequest): boolean {
  if (!object(request) || !text(request.user_id) || !text(request.scan_id) ||
      !Number.isSafeInteger(request.scan_revision) || request.scan_revision < 0 ||
      !text(request.idempotency_key) || !text(request.source_policy_id) ||
      !Number.isSafeInteger(request.source_policy_revision) || request.source_policy_revision < 0 ||
      !Array.isArray(request.items) || request.items.length === 0) return false;
  if (request.wait_timeout !== undefined &&
      (!finiteNumber(request.wait_timeout) || request.wait_timeout < 0 || request.wait_timeout > 30)) return false;
  if (request.scan_authority_token !== undefined && !text(request.scan_authority_token)) return false;
  if (request.profiles !== undefined && (!Array.isArray(request.profiles) || request.profiles.some((profile) =>
    !object(profile) || !text(profile.profile_id) || !text(profile.profile_hash) ||
    !/^[0-9a-f]{64}$/i.test(profile.profile_hash) || !text(profile.source_id) ||
    !Number.isSafeInteger(profile.profile_revision) || profile.profile_revision < 0))) return false;
  const ids = new Set<string>();
  for (const item of request.items) {
    if (!object(item) || !text(item.item_id) || ids.has(item.item_id) ||
        !Number.isSafeInteger(item.item_revision) || item.item_revision < 0 ||
        !text(item.name_zh) || !Array.isArray(item.validation_issues) ||
        item.validation_issues.some((issue) => !text(issue))) return false;
    if (item.identity_confirmation_required !== undefined &&
        typeof item.identity_confirmation_required !== 'boolean') return false;
    if (item.identity_confirmation_source !== undefined && item.identity_confirmation_source !== 'user') return false;
    if (item.identity_confirmation_id !== undefined && !text(item.identity_confirmation_id)) return false;
    if ((item.identity_confirmation_source === 'user') !== (item.identity_confirmation_id !== undefined) ||
        (item.identity_confirmation_source === 'user' && item.identity_confirmation_required !== false)) return false;
    ids.add(item.item_id);
    for (const key of ['confidence', 'weight_confidence', 'estimated_weight_g'] as const) {
      const value = item[key];
      if (value !== null && !finiteNumber(value)) return false;
    }
  }
  return true;
}

function parseSuccess(value: unknown): NutritionEnrichmentResponse {
  if (!object(value) || typeof value.status !== 'string' ||
      !['accepted', 'partial', 'complete', 'success', 'pending', 'timeout', 'rate_limited',
        'upstream_error', 'busy', 'invalid_output', 'source_conflict', 'not_found'].includes(value.status) ||
      !(value.request_id === null || text(value.request_id)) || typeof value.replayed !== 'boolean' ||
      !(value.result === null || (object(value.result) && value.result.schema_version === 'NutritionEnrichmentRouteV1' &&
        Array.isArray(value.result.items) && object(value.result.nutrition_coverage))) ||
      !(value.error === null || (object(value.error) && text(value.error.code) && text(value.error.message)))) {
    throw new NutritionEnrichmentApiError('營養補全回傳格式不相容', 200, 'invalid_response');
  }
  return value as unknown as NutritionEnrichmentResponse;
}

/**
 * Call the isolated enrichment route. The explicit flag defaults to false so
 * legacy scanner flows cannot accidentally spend web quota before the v2 UI
 * and backend capability negotiation are complete.
 */
export async function requestNutritionEnrichment(
  apiBaseUrl: string,
  request: NutritionEnrichmentRequest,
  auth?: ApiAuth,
  options?: { enabled?: boolean; isCurrentSession?: () => boolean },
): Promise<NutritionEnrichmentResponse> {
  if (options?.enabled !== true) {
    throw new NutritionEnrichmentApiError('自動營養補全尚未啟用', 503, 'feature_disabled');
  }
  if (!validRequest(request)) {
    throw new NutritionEnrichmentApiError('營養補全請求格式不正確', 0, 'invalid_request');
  }
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl.replace(/\/$/, '')}/nutrition/enrichment`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(auth?.accessToken ? { Authorization: `Bearer ${auth.accessToken}` } : {}),
      },
      body: JSON.stringify(request),
    });
  } catch {
    throw new NutritionEnrichmentApiError('無法連線到營養補全服務', 0, 'network_error');
  }
  if (!options.isCurrentSession || options.isCurrentSession()) reportUnauthorized(response);
  let data: unknown;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) {
    const error = object(data) && object(data.error) ? data.error : {};
    throw new NutritionEnrichmentApiError(
      text(error.message) ? error.message : `營養補全服務錯誤（HTTP ${response.status}）`,
      response.status,
      text(error.code) ? error.code : 'http_error',
      response.headers.get('Retry-After'),
    );
  }
  return parseSuccess(data);
}

