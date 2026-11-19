import type { ApiAuth } from './api';

export type IdentityConfirmationItem = {
  item_id: string;
  item_revision: number;
  name_zh: string;
  food_state: string | null;
  preparation_method: string | null;
  components_scope: string | null;
  validation_issues: string[];
  identity_confirmation_required?: boolean;
  identity_confirmation_source?: 'user';
  identity_confirmation_id?: string;
};

export type IdentityConfirmationContext = {
  status: 'persisted';
  scan_id: string;
  scan_revision: number;
  items: IdentityConfirmationItem[];
};

export type NutritionIdentityConfirmationRequest = {
  scan_id: string;
  scan_revision: number;
  item_id: string;
  item_revision: number;
  name_zh: string;
  idempotency_key: string;
};

export type NutritionIdentityConfirmationResponse = {
  status: 'confirmed';
  decision: 'confirm' | 'correct';
  confirmation_id: string;
  scan_id: string;
  source_scan_revision: number;
  issued_scan_revision: number;
  item_id: string;
  source_item_revision: number;
  issued_item_revision: number;
  name_zh: string;
  identity_confirmation_required: false;
  identity_confirmation_source: 'user';
  identity_confirmation_id: string;
  expires_at: number;
  replayed: boolean;
  local_lookup: {
    status: 'matched' | 'source_conflict' | 'incomplete_profile' | 'incompatible' | 'no_local_mapping';
    item: Record<string, unknown> | null;
  };
};

export class NutritionIdentityConfirmationApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfter: string | null;

  constructor(message: string, status: number, code: string, retryAfter: string | null = null) {
    super(message);
    this.name = 'NutritionIdentityConfirmationApiError';
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  const expected = new Set(keys);
  return Object.keys(value).length === expected.size && Object.keys(value).every((key) => expected.has(key));
}

function text(value: unknown, maximum = 256): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= maximum &&
    value.trim() === value && !/[\u0000-\u001f\u007f]/.test(value);
}

function integer(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

export function buildNutritionIdentityConfirmationRequest(params: {
  context: IdentityConfirmationContext;
  itemId: string;
  name: string;
  idempotencyKey: string;
}): NutritionIdentityConfirmationRequest {
  const { context, itemId, name, idempotencyKey } = params;
  const item = context?.items?.find((entry) => entry.item_id === itemId);
  if (!context || context.status !== 'persisted' || !text(context.scan_id) ||
      !integer(context.scan_revision) || !item || !integer(item.item_revision) ||
      item.identity_confirmation_required !== true || !Array.isArray(item.validation_issues) ||
      item.validation_issues.length !== 0 || !text(itemId, 256) || !text(name, 120) ||
      !text(idempotencyKey, 128)) {
    throw new NutritionIdentityConfirmationApiError('食材名稱確認內容不正確', 0, 'invalid_request');
  }
  return {
    scan_id: context.scan_id,
    scan_revision: context.scan_revision,
    item_id: item.item_id,
    item_revision: item.item_revision,
    name_zh: name,
    idempotency_key: idempotencyKey,
  };
}

function validResponse(value: unknown): value is NutritionIdentityConfirmationResponse {
  if (!object(value) || !exactKeys(value, [
    'status', 'decision', 'confirmation_id', 'scan_id', 'source_scan_revision',
    'issued_scan_revision', 'item_id', 'source_item_revision', 'issued_item_revision',
    'name_zh', 'identity_confirmation_required', 'identity_confirmation_source',
    'identity_confirmation_id', 'expires_at', 'replayed', 'local_lookup',
  ])) return false;
  if (!object(value.local_lookup) || !exactKeys(value.local_lookup, ['status', 'item']) ||
      !['matched', 'source_conflict', 'incomplete_profile', 'incompatible', 'no_local_mapping']
        .includes(String(value.local_lookup.status))) return false;
  if (value.local_lookup.status === 'matched') {
    const item = value.local_lookup.item;
    if (!object(item) || item.item_id !== value.item_id ||
        item.item_revision !== value.issued_item_revision || item.origin !== 'local' || item.status !== 'accepted') return false;
  } else if (value.local_lookup.item !== null) return false;
  return value.status === 'confirmed' && ['confirm', 'correct'].includes(String(value.decision)) &&
    text(value.confirmation_id) && text(value.scan_id) && integer(value.source_scan_revision) &&
    integer(value.issued_scan_revision) && value.issued_scan_revision === value.source_scan_revision + 1 &&
    text(value.item_id) && integer(value.source_item_revision) &&
    integer(value.issued_item_revision) && value.issued_item_revision === value.source_item_revision + 1 &&
    text(value.name_zh, 120) && value.identity_confirmation_required === false &&
    value.identity_confirmation_source === 'user' && text(value.identity_confirmation_id) &&
    typeof value.expires_at === 'number' && Number.isFinite(value.expires_at) &&
    typeof value.replayed === 'boolean';
}

function reportUnauthorized(response: Response, isCurrentSession?: () => boolean): void {
  if (response.status === 401 && (!isCurrentSession || isCurrentSession()) &&
      typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(new Event('nutrilens:unauthorized'));
  }
}

export async function confirmNutritionIdentity(
  apiBaseUrl: string,
  request: NutritionIdentityConfirmationRequest,
  auth?: ApiAuth,
  options?: { enabled?: boolean; isCurrentSession?: () => boolean },
): Promise<NutritionIdentityConfirmationResponse> {
  if (options?.enabled !== true) {
    throw new NutritionIdentityConfirmationApiError('食材名稱確認尚未啟用', 503, 'feature_disabled');
  }
  if (!object(request) || !exactKeys(request, [
    'scan_id', 'scan_revision', 'item_id', 'item_revision', 'name_zh', 'idempotency_key',
  ]) || !text(request.scan_id) || !integer(request.scan_revision) || !text(request.item_id) ||
      !integer(request.item_revision) || !text(request.name_zh, 120) ||
      !text(request.idempotency_key, 128)) {
    throw new NutritionIdentityConfirmationApiError('食材名稱確認請求格式不正確', 0, 'invalid_request');
  }
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl.replace(/\/$/, '')}/nutrition/identity/confirmation`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(auth?.accessToken ? { Authorization: `Bearer ${auth.accessToken}` } : {}),
      },
      body: JSON.stringify(request),
    });
  } catch {
    throw new NutritionIdentityConfirmationApiError('無法連線到食材名稱確認服務', 0, 'network_error');
  }
  reportUnauthorized(response, options?.isCurrentSession);
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = object(data) && object(data.error) ? data.error : {};
    throw new NutritionIdentityConfirmationApiError(
      text(error.message) ? error.message : `食材名稱確認服務錯誤（HTTP ${response.status}）`,
      response.status,
      text(error.code) ? error.code : 'http_error',
      response.headers.get('Retry-After'),
    );
  }
  if (!validResponse(data)) {
    throw new NutritionIdentityConfirmationApiError('食材名稱確認回傳格式不相容', 200, 'invalid_response');
  }
  return data;
}
