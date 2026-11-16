import type { ApiAuth } from './api';
import { reportUnauthorized } from './auth';
import type {
  NutritionFdcCandidateSnapshotResponse,
} from './nutrition-fdc-candidate-api';

export type NutritionFdcDecision = {
  item_id: string;
  decision: 'confirm' | 'reject' | 'defer';
  candidate_fdc_id: string | null;
};

export type NutritionFdcConfirmationRequest = {
  scan_id: string;
  scan_revision: number;
  idempotency_key: string;
  confirmation: {
    schema_version: 'FdcCandidateConfirmationV1';
    snapshot_digest: string;
    scan_revision: number;
    items: NutritionFdcDecision[];
  };
};

export type NutritionFdcConfirmationItem = {
  item_id: string;
  status: 'confirmed_pending_revision' | 'rejected' | 'confirmation_required';
  item_revision: number;
  confirmed_fdc_id: string | null;
  snapshot_digest: string;
  scan_revision: number;
  identity_digest: string;
  requires_new_scan_revision: boolean;
  requires_user_confirmation: boolean;
};

export type NutritionFdcConfirmationResponse = {
  status: 'confirmed_pending_revision' | 'rejected' | 'confirmation_required';
  confirmation_id: string;
  scan_id: string;
  scan_revision: number;
  issued_scan_revision: number | null;
  requires_detail_replay: boolean;
  snapshot_digest: string;
  items: NutritionFdcConfirmationItem[];
  requires_new_scan_revision: boolean;
  photo_confidence_changed: false;
  replayed: boolean;
};

export class NutritionFdcConfirmationApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfter: string | null;

  constructor(message: string, status: number, code: string, retryAfter: string | null = null) {
    super(message);
    this.name = 'NutritionFdcConfirmationApiError';
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

type DecisionInput = Omit<NutritionFdcDecision, 'candidate_fdc_id'> & {
  candidate_fdc_id?: string | null;
};

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

function validFdcId(value: unknown): value is string {
  return text(value, 18) && /^[1-9][0-9]*$/.test(value);
}

function candidateMap(snapshot: NutritionFdcCandidateSnapshotResponse): Map<string, Set<string>> {
  return new Map(snapshot.snapshot.snapshot.items.map((item) => [
    item.item_id,
    new Set(item.candidates.map((candidate) => candidate.fdcId)),
  ]));
}

export function buildNutritionFdcConfirmationRequest(params: {
  snapshot: NutritionFdcCandidateSnapshotResponse;
  idempotencyKey: string;
  decisions: DecisionInput[];
}): NutritionFdcConfirmationRequest {
  const { snapshot, idempotencyKey, decisions } = params;
  if (!object(params) || !text(idempotencyKey, 128) || !Array.isArray(decisions)) {
    throw new NutritionFdcConfirmationApiError('FDC 候選確認內容不正確', 0, 'invalid_request');
  }
  const envelope = snapshot?.snapshot?.snapshot;
  const reference = snapshot?.snapshot;
  if (!envelope || !reference || envelope.scan_revision !== reference.scan_revision ||
      envelope.snapshot_digest !== reference.snapshot_digest || !digest(reference.snapshot_digest)) {
    throw new NutritionFdcConfirmationApiError('FDC 候選快照已失效', 0, 'invalid_request');
  }
  const available = candidateMap(snapshot);
  if (decisions.length !== available.size) {
    throw new NutritionFdcConfirmationApiError('每個項目都需要明確決定', 0, 'invalid_request');
  }
  const seen = new Set<string>();
  const items = decisions.map((input) => {
    if (!object(input) || !text(input.item_id, 128) || seen.has(input.item_id) ||
        !available.has(input.item_id) || !['confirm', 'reject', 'defer'].includes(input.decision)) {
      throw new NutritionFdcConfirmationApiError('FDC 候選決定不正確', 0, 'invalid_request');
    }
    seen.add(input.item_id);
    const candidateId = input.candidate_fdc_id ?? null;
    if (input.decision === 'confirm') {
      if (!validFdcId(candidateId) || !available.get(input.item_id)?.has(candidateId)) {
        throw new NutritionFdcConfirmationApiError('只能確認畫面列出的 FDC 候選', 0, 'invalid_request');
      }
      return { item_id: input.item_id, decision: input.decision, candidate_fdc_id: candidateId };
    }
    if (candidateId !== null) {
      throw new NutritionFdcConfirmationApiError('拒絕或保留項目不可附帶候選 ID', 0, 'invalid_request');
    }
    return { item_id: input.item_id, decision: input.decision, candidate_fdc_id: null };
  });
  const orderedItems = envelope.items.map((item) => {
    const decision = items.find((entry) => entry.item_id === item.item_id);
    if (!decision) throw new NutritionFdcConfirmationApiError('候選項目集合不一致', 0, 'invalid_request');
    return decision;
  });
  return {
    scan_id: reference.scan_id,
    scan_revision: reference.scan_revision,
    idempotency_key: idempotencyKey,
    confirmation: {
      schema_version: 'FdcCandidateConfirmationV1',
      snapshot_digest: reference.snapshot_digest,
      scan_revision: reference.scan_revision,
      items: orderedItems,
    },
  };
}

function validConfirmationItem(value: unknown, snapshotItem: NutritionFdcCandidateSnapshotResponse['snapshot']['snapshot']['items'][number],
  snapshot: NutritionFdcCandidateSnapshotResponse): value is NutritionFdcConfirmationItem {
  if (!object(value) || !exactKeys(value, [
    'item_id', 'status', 'item_revision', 'confirmed_fdc_id', 'snapshot_digest', 'scan_revision',
    'identity_digest', 'requires_new_scan_revision', 'requires_user_confirmation',
  ]) || value.item_id !== snapshotItem.item_id || value.item_revision !== snapshotItem.item_revision ||
      value.scan_revision !== snapshot.snapshot.scan_revision || value.snapshot_digest !== snapshot.snapshot.snapshot_digest ||
      value.identity_digest !== snapshotItem.identity_digest ||
      !['confirmed_pending_revision', 'rejected', 'confirmation_required'].includes(String(value.status)) ||
      typeof value.requires_new_scan_revision !== 'boolean' || typeof value.requires_user_confirmation !== 'boolean') {
    return false;
  }
  if (value.status === 'confirmed_pending_revision') {
    return validFdcId(value.confirmed_fdc_id) && snapshotItem.candidates.some((item) => item.fdcId === value.confirmed_fdc_id) &&
      value.requires_new_scan_revision === true && value.requires_user_confirmation === false;
  }
  return value.confirmed_fdc_id === null && value.requires_new_scan_revision === false &&
    value.requires_user_confirmation === (value.status === 'confirmation_required');
}

function parseResponse(value: unknown, request: NutritionFdcConfirmationRequest,
  snapshot: NutritionFdcCandidateSnapshotResponse): NutritionFdcConfirmationResponse {
  const invalid = () => new NutritionFdcConfirmationApiError('FDC 候選確認回傳格式不相容', 200, 'invalid_response');
  if (!object(value) || !exactKeys(value, [
    'status', 'confirmation_id', 'scan_id', 'scan_revision', 'issued_scan_revision',
    'requires_detail_replay', 'snapshot_digest', 'items', 'requires_new_scan_revision',
    'photo_confidence_changed', 'replayed',
  ]) || !['confirmed_pending_revision', 'rejected', 'confirmation_required'].includes(String(value.status)) ||
      !text(value.confirmation_id, 128) || value.scan_id !== request.scan_id ||
      value.scan_revision !== request.scan_revision || value.snapshot_digest !== request.confirmation.snapshot_digest ||
      typeof value.requires_detail_replay !== 'boolean' || typeof value.requires_new_scan_revision !== 'boolean' ||
      value.photo_confidence_changed !== false || typeof value.replayed !== 'boolean' || !Array.isArray(value.items)) {
    throw invalid();
  }
  const issuedRevision = value.issued_scan_revision;
  const hasConfirmed = request.confirmation.items.some((item) => item.decision === 'confirm');
  if ((issuedRevision !== null && (!integer(issuedRevision) || issuedRevision !== request.scan_revision + 1)) ||
      value.requires_new_scan_revision !== (issuedRevision !== null) ||
      value.requires_detail_replay !== hasConfirmed || value.requires_new_scan_revision !== hasConfirmed ||
      value.items.length !== snapshot.snapshot.snapshot.items.length) {
    throw invalid();
  }
  const resultItems = value.items as unknown[];
  if (!snapshot.snapshot.snapshot.items.every((item, index) => validConfirmationItem(resultItems[index], item, snapshot))) {
    throw invalid();
  }
  const requestedByItem = new Map(request.confirmation.items.map((item) => [item.item_id, item]));
  if (!resultItems.every((entry) => {
    if (!object(entry)) return false;
    const decision = requestedByItem.get(String(entry.item_id));
    if (!decision) return false;
    if (decision.decision === 'confirm') {
      return entry.status === 'confirmed_pending_revision' && entry.confirmed_fdc_id === decision.candidate_fdc_id;
    }
    return entry.status === (decision.decision === 'reject' ? 'rejected' : 'confirmation_required') &&
      entry.confirmed_fdc_id === null;
  })) throw invalid();
  const normalizedStatus = resultItems.some((item) => object(item) && item.status === 'confirmed_pending_revision')
    ? 'confirmed_pending_revision'
    : resultItems.some((item) => object(item) && item.status === 'confirmation_required')
      ? 'confirmation_required' : 'rejected';
  if (value.status !== normalizedStatus) throw invalid();
  return value as unknown as NutritionFdcConfirmationResponse;
}

export async function confirmNutritionFdcCandidates(
  apiBaseUrl: string,
  request: NutritionFdcConfirmationRequest,
  snapshot: NutritionFdcCandidateSnapshotResponse,
  auth?: ApiAuth,
  options?: { enabled?: boolean; isCurrentSession?: () => boolean },
): Promise<NutritionFdcConfirmationResponse> {
  if (options?.enabled !== true) {
    throw new NutritionFdcConfirmationApiError('FDC 候選確認尚未啟用', 503, 'feature_disabled');
  }
  if (!object(request) || !exactKeys(request, ['scan_id', 'scan_revision', 'idempotency_key', 'confirmation']) ||
      !object(request.confirmation) || !exactKeys(request.confirmation, ['schema_version', 'snapshot_digest', 'scan_revision', 'items']) ||
      !Array.isArray(request.confirmation.items) || !text(request.idempotency_key, 128) ||
      request.scan_id !== snapshot.snapshot.scan_id || request.scan_revision !== snapshot.snapshot.scan_revision ||
      request.confirmation.snapshot_digest !== snapshot.snapshot.snapshot_digest ||
      request.confirmation.schema_version !== 'FdcCandidateConfirmationV1' ||
      request.confirmation.scan_revision !== request.scan_revision ||
      request.confirmation.items.some((item) => !object(item) || !exactKeys(item, ['item_id', 'decision', 'candidate_fdc_id']))) {
    throw new NutritionFdcConfirmationApiError('FDC 候選確認參考已失效', 0, 'invalid_request');
  }
  try {
    const rebuilt = buildNutritionFdcConfirmationRequest({
      snapshot, idempotencyKey: request.idempotency_key, decisions: request.confirmation.items,
    });
    if (JSON.stringify(rebuilt) !== JSON.stringify(request)) {
      throw new NutritionFdcConfirmationApiError('FDC 候選確認內容不正確', 0, 'invalid_request');
    }
  } catch (error) {
    if (error instanceof NutritionFdcConfirmationApiError) throw error;
    throw new NutritionFdcConfirmationApiError('FDC 候選確認內容不正確', 0, 'invalid_request');
  }
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl.replace(/\/$/, '')}/nutrition/fdc/confirmation`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(auth?.accessToken ? { Authorization: `Bearer ${auth.accessToken}` } : {}),
      },
      body: JSON.stringify(request),
    });
  } catch {
    throw new NutritionFdcConfirmationApiError('無法連線到 FDC 候選確認服務', 0, 'network_error');
  }
  if (response.status === 401 && (!options.isCurrentSession || options.isCurrentSession())) reportUnauthorized();
  let data: unknown;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) {
    const error = object(data) && object(data.error) ? data.error : {};
    throw new NutritionFdcConfirmationApiError(
      text(error.message) ? error.message : `FDC 候選確認錯誤（HTTP ${response.status}）`,
      response.status,
      text(error.code) ? error.code : 'http_error',
      response.headers.get('Retry-After'),
    );
  }
  if (response.status !== 200 && response.status !== 202) {
    throw new NutritionFdcConfirmationApiError('FDC 候選確認回傳狀態不相容', response.status, 'invalid_response');
  }
  return parseResponse(data, request, snapshot);
}
