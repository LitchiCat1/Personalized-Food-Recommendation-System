import type { ApiAuth } from './api';
import { reportUnauthorized } from './auth';

/**
 * References used by the disabled-by-default FDC confirmation flow.
 *
 * The browser never sends an FDC id, provider document, weight, or profile.
 * Those values are resolved from server-owned confirmation and scan records.
 */
export type NutritionFdcProfilePreviewRequest = {
  confirmation_id: string;
  scan_id: string;
  issued_scan_revision: number;
  item_id: string;
};

export type NutritionFdcProfilePreview = {
  nutrition_profile: Record<string, unknown>;
  portion: Record<string, unknown>;
  source_block: Record<string, unknown>;
  recognition_identity: Record<string, unknown>;
  source_identity: Record<string, unknown>;
};

export type NutritionFdcProfilePreviewResponse = {
  status: 'preview_ready';
  preview_id: string;
  confirmation_id: string;
  scan_id: string;
  issued_scan_revision: number;
  item_id: string;
  item_revision: number;
  snapshot_digest: string;
  source_id: string;
  source_policy_revision: number;
  fdc_id: string;
  weight_g: number;
  preview: NutritionFdcProfilePreview;
  photo_confidence_changed: false;
  profile_written: false;
};

export type NutritionFdcProfileAcceptRequest = {
  preview_id: string;
  idempotency_key: string;
};

export type NutritionFdcProfileAcceptResponse = {
  status: 'accepted';
  preview_id: string;
  profile: Record<string, unknown>;
  portion: Record<string, unknown>;
  profile_hash: string;
  replayed: boolean;
  photo_confidence_changed: false;
  profile_written: true;
};

export class NutritionFdcPreviewApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfter: string | null;

  constructor(message: string, status: number, code: string, retryAfter: string | null = null) {
    super(message);
    this.name = 'NutritionFdcPreviewApiError';
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function text(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.trim() === value &&
    !/[\u0000-\u001f\u007f]/.test(value);
}

function integer(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function positiveNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0;
}

function digest(value: unknown): value is string {
  return typeof value === 'string' && /^[0-9a-f]{64}$/i.test(value);
}

function exactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  const expected = new Set(keys);
  return Object.keys(value).length === expected.size && Object.keys(value).every((key) => expected.has(key));
}

function validPreviewRequest(request: NutritionFdcProfilePreviewRequest): boolean {
  return object(request) && exactKeys(request, ['confirmation_id', 'scan_id', 'issued_scan_revision', 'item_id']) &&
    text(request.confirmation_id) && text(request.scan_id) && integer(request.issued_scan_revision) && text(request.item_id);
}

function validAcceptRequest(request: NutritionFdcProfileAcceptRequest): boolean {
  return object(request) && exactKeys(request, ['preview_id', 'idempotency_key']) &&
    text(request.preview_id) && text(request.idempotency_key);
}

function parsePreview(
  value: unknown,
  request: NutritionFdcProfilePreviewRequest,
): NutritionFdcProfilePreviewResponse {
  if (!object(value) || !exactKeys(value, [
    'status', 'preview_id', 'confirmation_id', 'scan_id', 'issued_scan_revision', 'item_id',
    'item_revision', 'snapshot_digest', 'source_id', 'source_policy_revision', 'fdc_id',
    'weight_g', 'preview', 'photo_confidence_changed', 'profile_written',
  ]) || value.status !== 'preview_ready' || !text(value.preview_id) ||
      value.confirmation_id !== request.confirmation_id || value.scan_id !== request.scan_id ||
      value.issued_scan_revision !== request.issued_scan_revision || value.item_id !== request.item_id ||
      !integer(value.item_revision) || !digest(value.snapshot_digest) ||
      !text(value.source_id) || !integer(value.source_policy_revision) || !text(value.fdc_id) ||
      !positiveNumber(value.weight_g) || value.photo_confidence_changed !== false ||
      value.profile_written !== false || !object(value.preview)) {
    throw new NutritionFdcPreviewApiError('FDC 預覽回傳格式不相容', 200, 'invalid_response');
  }
  const preview = value.preview;
  if (!object(preview) || !exactKeys(preview, [
    'nutrition_profile', 'portion', 'source_block', 'recognition_identity', 'source_identity',
  ]) || !object(preview.nutrition_profile) || !object(preview.portion) ||
      !object(preview.source_block) || !object(preview.recognition_identity) ||
      !object(preview.source_identity)) {
    throw new NutritionFdcPreviewApiError('FDC 預覽回傳格式不相容', 200, 'invalid_response');
  }
  return value as unknown as NutritionFdcProfilePreviewResponse;
}

function parseAccept(value: unknown): NutritionFdcProfileAcceptResponse {
  if (!object(value) || value.status !== 'accepted' || !text(value.preview_id) ||
      !object(value.profile) || !object(value.portion) || !digest(value.profile_hash) ||
      typeof value.replayed !== 'boolean' || value.photo_confidence_changed !== false ||
      value.profile_written !== true) {
    throw new NutritionFdcPreviewApiError('FDC 營養資料回傳格式不相容', 200, 'invalid_response');
  }
  return value as unknown as NutritionFdcProfileAcceptResponse;
}

async function requestJson<T>(apiBaseUrl: string, path: string, body: object, auth: ApiAuth | undefined,
  parse: (value: unknown) => T,
  options?: { enabled?: boolean; isCurrentSession?: () => boolean }): Promise<T> {
  if (options?.enabled !== true) {
    throw new NutritionFdcPreviewApiError('FDC 營養預覽尚未啟用', 503, 'feature_disabled');
  }
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl.replace(/\/$/, '')}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(auth?.accessToken ? { Authorization: `Bearer ${auth.accessToken}` } : {}),
      },
      body: JSON.stringify(body),
    });
  } catch {
    throw new NutritionFdcPreviewApiError('無法連線到 FDC 預覽服務', 0, 'network_error');
  }
  if (response.status === 401 && (!options.isCurrentSession || options.isCurrentSession())) reportUnauthorized();
  let data: unknown;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) {
    const error = object(data) && object(data.error) ? data.error : {};
    throw new NutritionFdcPreviewApiError(
      text(error.message) ? error.message : `FDC 預覽服務錯誤（HTTP ${response.status}）`,
      response.status,
      text(error.code) ? error.code : 'http_error',
      response.headers.get('Retry-After'),
    );
  }
  return parse(data);
}

export function buildNutritionFdcProfilePreviewRequest(params: NutritionFdcProfilePreviewRequest): NutritionFdcProfilePreviewRequest {
  if (!validPreviewRequest(params)) {
    throw new NutritionFdcPreviewApiError('FDC 預覽請求格式不正確', 0, 'invalid_request');
  }
  return { ...params };
}

export async function requestNutritionFdcProfilePreview(
  apiBaseUrl: string,
  request: NutritionFdcProfilePreviewRequest,
  auth?: ApiAuth,
  options?: { enabled?: boolean; isCurrentSession?: () => boolean },
): Promise<NutritionFdcProfilePreviewResponse> {
  if (options?.enabled !== true) {
    throw new NutritionFdcPreviewApiError('FDC 營養預覽尚未啟用', 503, 'feature_disabled');
  }
  if (!validPreviewRequest(request)) {
    throw new NutritionFdcPreviewApiError('FDC 預覽請求格式不正確', 0, 'invalid_request');
  }
  return requestJson(apiBaseUrl, '/nutrition/fdc/profile-preview', request, auth,
    (value) => parsePreview(value, request), options);
}

export async function requestNutritionFdcProfileAccept(
  apiBaseUrl: string,
  request: NutritionFdcProfileAcceptRequest,
  auth?: ApiAuth,
  options?: { enabled?: boolean; isCurrentSession?: () => boolean },
): Promise<NutritionFdcProfileAcceptResponse> {
  if (options?.enabled !== true) {
    throw new NutritionFdcPreviewApiError('FDC 營養預覽尚未啟用', 503, 'feature_disabled');
  }
  if (!validAcceptRequest(request)) {
    throw new NutritionFdcPreviewApiError('FDC 營養確認請求格式不正確', 0, 'invalid_request');
  }
  return requestJson(apiBaseUrl, '/nutrition/fdc/profile-accept', request, auth, parseAccept, options);
}

