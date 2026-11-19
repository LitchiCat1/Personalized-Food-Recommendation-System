import type { ApiAuth } from './api';
import { reportUnauthorized } from './auth';

export type NutritionFdcCandidateRequest = {
  scan_id: string;
  scan_revision: number;
};

export type NutritionFdcCandidate = {
  fdcId: string;
  description: string;
  dataType: 'Foundation' | 'SR Legacy' | 'Survey (FNDDS)';
  brandOwner: string | null;
  foodCategory: string | null;
};

export type NutritionFdcCandidateItem = {
  item_id: string;
  item_revision: number;
  identity_digest: string;
  recognition_identity: {
    name_zh: string;
    food_state: string | null;
    preparation_method: string | null;
    components_scope: string | null;
    brand: string | null;
    variant: string | null;
  };
  candidates: NutritionFdcCandidate[];
};

export type NutritionFdcCandidateSnapshotResponse = {
  status: 'available' | 'empty';
  selection?: {
    schema_version: 'ReviewedFdcSelectionV1';
    items: { item_id: string; weight_g: number | null; reason: string }[];
    user_confirmation_required: true;
    photo_confidence_changed: false;
  };
  snapshot: {
    scan_id: string;
    scan_revision: number;
    snapshot_digest: string;
    expires_at: number;
    snapshot: {
      schema_version: 'FdcCandidateSnapshotV1';
      scan_revision: number;
      item_set_digest: string;
      snapshot_digest: string;
      items: NutritionFdcCandidateItem[];
    };
  };
};

export class NutritionFdcCandidateApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfter: string | null;

  constructor(message: string, status: number, code: string, retryAfter: string | null = null) {
    super(message);
    this.name = 'NutritionFdcCandidateApiError';
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

function digest(value: unknown): value is string {
  return typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
}

function validRequest(request: NutritionFdcCandidateRequest): boolean {
  return object(request) && exactKeys(request, ['scan_id', 'scan_revision']) &&
    text(request.scan_id) && integer(request.scan_revision);
}

const IDENTITY_FIELDS = [
  'name_zh', 'food_state', 'preparation_method', 'components_scope', 'brand', 'variant',
];
const IDENTITY_ENUMS: Record<string, Set<string>> = {
  food_state: new Set(['prepared', 'raw', 'dry', 'unknown']),
  preparation_method: new Set(['boiled', 'stir_fried', 'pan_fried', 'deep_fried', 'roasted', 'braised', 'steamed', 'mixed', 'unknown']),
  components_scope: new Set(['food_only', 'noodles_only', 'whole_dish_with_broth', 'with_sides', 'unknown']),
};

function validIdentity(value: unknown): value is NutritionFdcCandidateItem['recognition_identity'] {
  if (!object(value) || !exactKeys(value, IDENTITY_FIELDS)) return false;
  if (!text(value.name_zh, 300)) return false;
  return IDENTITY_FIELDS.slice(1).every((field) => {
    const fieldValue = value[field];
    return fieldValue === null || (text(fieldValue, 300) &&
      (!IDENTITY_ENUMS[field] || IDENTITY_ENUMS[field].has(fieldValue)));
  });
}

const CANDIDATE_DATA_TYPES = new Set(['Foundation', 'SR Legacy', 'Survey (FNDDS)']);

function validCandidate(value: unknown): value is NutritionFdcCandidate {
  if (!object(value) || !exactKeys(value, ['fdcId', 'description', 'dataType', 'brandOwner', 'foodCategory']) ||
      !text(value.fdcId, 18) || !/^[1-9][0-9]*$/.test(value.fdcId) ||
      !text(value.description, 300) || !text(value.dataType, 64) || !CANDIDATE_DATA_TYPES.has(value.dataType)) {
    return false;
  }
  return ['brandOwner', 'foodCategory'].every((field) => value[field] === null || text(value[field], 300));
}

function validItem(value: unknown): value is NutritionFdcCandidateItem {
  if (!object(value) || !exactKeys(value, [
    'item_id', 'item_revision', 'identity_digest', 'recognition_identity', 'candidates',
  ]) || !text(value.item_id, 128) || !integer(value.item_revision) || !digest(value.identity_digest) ||
      !validIdentity(value.recognition_identity) || !Array.isArray(value.candidates) || value.candidates.length > 10 ||
      !value.candidates.every(validCandidate)) {
    return false;
  }
  const ids = value.candidates.map((candidate) => candidate.fdcId);
  return new Set(ids).size === ids.length;
}

function parseResponse(value: unknown, request: NutritionFdcCandidateRequest): NutritionFdcCandidateSnapshotResponse {
  const invalid = () => new NutritionFdcCandidateApiError('FDC 候選參考回傳格式不相容', 200, 'invalid_response');
  if (!object(value) || !exactKeys(value, ['status', 'snapshot']) ||
      !['available', 'empty'].includes(String(value.status)) || !object(value.snapshot) ||
      !exactKeys(value.snapshot, ['scan_id', 'scan_revision', 'snapshot_digest', 'expires_at', 'snapshot'])) {
    throw invalid();
  }

  const envelope = value.snapshot;
  if (!text(envelope.scan_id) || envelope.scan_id !== request.scan_id ||
      !integer(envelope.scan_revision) || envelope.scan_revision !== request.scan_revision ||
      !digest(envelope.snapshot_digest) || typeof envelope.expires_at !== 'number' ||
      !Number.isFinite(envelope.expires_at) || envelope.expires_at <= 0 || !object(envelope.snapshot) ||
      !exactKeys(envelope.snapshot, ['schema_version', 'scan_revision', 'item_set_digest', 'snapshot_digest', 'items'])) {
    throw invalid();
  }

  const snapshot = envelope.snapshot;
  if (snapshot.schema_version !== 'FdcCandidateSnapshotV1' ||
      !integer(snapshot.scan_revision) || snapshot.scan_revision !== request.scan_revision ||
      !digest(snapshot.item_set_digest) || !digest(snapshot.snapshot_digest) ||
      snapshot.snapshot_digest !== envelope.snapshot_digest || !Array.isArray(snapshot.items) ||
      snapshot.items.length === 0 || snapshot.items.length > 64 || !snapshot.items.every(validItem)) {
    throw invalid();
  }
  const itemIds = snapshot.items.map((item) => item.item_id);
  if (new Set(itemIds).size !== itemIds.length) throw invalid();

  const hasCandidates = snapshot.items.some((item) => item.candidates.length > 0);
  if ((value.status === 'available') !== hasCandidates) throw invalid();
  return value as unknown as NutritionFdcCandidateSnapshotResponse;
}

async function requestSnapshot(
  apiBaseUrl: string,
  request: NutritionFdcCandidateRequest,
  auth: ApiAuth | undefined,
  method: 'POST' | 'GET',
  options?: { enabled?: boolean; isCurrentSession?: () => boolean; reviewedSelection?: boolean },
): Promise<NutritionFdcCandidateSnapshotResponse> {
  if (options?.enabled !== true) {
    throw new NutritionFdcCandidateApiError('FDC 候選搜尋尚未啟用', 503, 'feature_disabled');
  }
  if (!validRequest(request)) {
    throw new NutritionFdcCandidateApiError('FDC 候選參考請求格式不正確', 0, 'invalid_request');
  }

  const baseUrl = apiBaseUrl.replace(/\/$/, '');
  const url = method === 'POST'
    ? `${baseUrl}/nutrition/fdc/${options?.reviewedSelection ? 'reviewed-selection' : 'candidates'}`
    : `${baseUrl}/nutrition/fdc/candidates?scan_id=${encodeURIComponent(request.scan_id)}&scan_revision=${request.scan_revision}`;
  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: {
        ...(method === 'POST' ? { 'Content-Type': 'application/json' } : {}),
        ...(auth?.accessToken ? { Authorization: `Bearer ${auth.accessToken}` } : {}),
      },
      ...(method === 'POST' ? { body: JSON.stringify(request) } : {}),
    });
  } catch {
    throw new NutritionFdcCandidateApiError('無法連線到 FDC 候選服務', 0, 'network_error');
  }
  if (response.status === 401 && (!options?.isCurrentSession || options.isCurrentSession())) reportUnauthorized();
  let data: unknown;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) {
    const error = object(data) && object(data.error) ? data.error : {};
    throw new NutritionFdcCandidateApiError(
      text(error.message) ? error.message : `FDC 候選服務錯誤（HTTP ${response.status}）`,
      response.status,
      text(error.code) ? error.code : 'http_error',
      response.headers.get('Retry-After'),
    );
  }
  if (!options?.reviewedSelection) return parseResponse(data, request);
  const invalid = () => new NutritionFdcCandidateApiError('營養來源配對回傳格式不相容', 200, 'invalid_response');
  if (!object(data) || !exactKeys(data, ['status', 'snapshot', 'selection']) || !object(data.selection)) throw invalid();
  const parsed = parseResponse({ status: data.status, snapshot: data.snapshot }, request);
  const selection = data.selection;
  if (!exactKeys(selection, ['schema_version', 'items', 'user_confirmation_required', 'photo_confidence_changed']) ||
      selection.schema_version !== 'ReviewedFdcSelectionV1' || selection.user_confirmation_required !== true ||
      selection.photo_confidence_changed !== false || !Array.isArray(selection.items) ||
      selection.items.length !== parsed.snapshot.snapshot.items.length) throw invalid();
  const reasons = new Set(['reviewed_match', 'identity_required', 'weight_required', 'local_priority',
    'no_reviewed_source', 'ambiguous_reviewed_source']);
  const ids = new Set<string>();
  for (const entry of selection.items) {
    if (!object(entry) || !exactKeys(entry, ['item_id', 'weight_g', 'reason']) ||
        !text(entry.item_id) || ids.has(entry.item_id) || !reasons.has(String(entry.reason)) ||
        (entry.weight_g !== null && (typeof entry.weight_g !== 'number' ||
          !Number.isFinite(entry.weight_g) || entry.weight_g <= 0 || entry.weight_g > 2000))) throw invalid();
    const item = parsed.snapshot.snapshot.items.find((item) => item.item_id === entry.item_id);
    if (!item || item.candidates.length > 1 ||
        (entry.reason === 'reviewed_match') !== (item.candidates.length === 1) ||
        (entry.reason === 'reviewed_match' && entry.weight_g === null)) throw invalid();
    ids.add(entry.item_id);
  }
  return { ...parsed, selection: selection as unknown as NonNullable<NutritionFdcCandidateSnapshotResponse['selection']> };
}

export function buildNutritionFdcCandidateRequest(params: NutritionFdcCandidateRequest): NutritionFdcCandidateRequest {
  if (!validRequest(params)) {
    throw new NutritionFdcCandidateApiError('FDC 候選參考請求格式不正確', 0, 'invalid_request');
  }
  return { scan_id: params.scan_id, scan_revision: params.scan_revision };
}

export function createNutritionFdcCandidateSnapshot(
  apiBaseUrl: string,
  request: NutritionFdcCandidateRequest,
  auth?: ApiAuth,
  options?: { enabled?: boolean; isCurrentSession?: () => boolean },
): Promise<NutritionFdcCandidateSnapshotResponse> {
  return requestSnapshot(apiBaseUrl, request, auth, 'POST', options);
}

export function getNutritionFdcCandidateSnapshot(
  apiBaseUrl: string,
  request: NutritionFdcCandidateRequest,
  auth?: ApiAuth,
  options?: { enabled?: boolean; isCurrentSession?: () => boolean },
): Promise<NutritionFdcCandidateSnapshotResponse> {
  return requestSnapshot(apiBaseUrl, request, auth, 'GET', options);
}

export function selectReviewedNutritionFdcSource(
  apiBaseUrl: string,
  request: NutritionFdcCandidateRequest,
  auth?: ApiAuth,
  options?: { enabled?: boolean; isCurrentSession?: () => boolean },
): Promise<NutritionFdcCandidateSnapshotResponse> {
  return requestSnapshot(apiBaseUrl, request, auth, 'POST', { ...options, reviewedSelection: true });
}
