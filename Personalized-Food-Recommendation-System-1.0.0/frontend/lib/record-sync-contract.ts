import type { DetectedFood } from '@/constants/mock-data';
import type { MealType } from './meal';
import type { NutritionRecordCreateV2 } from './nutrition-contract';

export type RecordSource = 'camera' | 'manual' | 'nutrition-label';
export type QueuedNutritionRecordCreateV2 = NutritionRecordCreateV2 & {
  client_record_id: string;
  timestamp: string;
  source: RecordSource;
  meal_type: MealType;
};
type PendingSyncBase = {
  id: string;
  userId: string;
  clientRecordId: string;
  source: RecordSource;
  error: string;
  attempts: number;
  createdAt: string;
  updatedAt: string;
  recordTimestamp: string;
  mealType: MealType;
  apiBaseUrl?: string;
};
export type PendingRecordSync = PendingSyncBase & {
  nutritionContractVersion: 1;
  foods: DetectedFood[];
};
export type PendingV2RecordSync = PendingSyncBase & {
  nutritionContractVersion: 2;
  payload: QueuedNutritionRecordCreateV2;
};
export type VersionedPendingRecordSync = PendingRecordSync | PendingV2RecordSync;
export type RecordSyncQueueEnvelope = {
  queue_schema_version: 2;
  entries: VersionedPendingRecordSync[];
};
export const RECORD_SYNC_QUEUE_KEY = 'nutrilens.pendingRecordSyncQueue.v2';
export const LEGACY_RECORD_SYNC_QUEUE_KEY = 'nutrilens.pendingRecordSyncQueue.v1';
export const MAX_RECORD_SYNC_ATTEMPTS = 5;
export const RECORD_SYNC_QUEUE_LOCK_NAME = 'nutrilens.pendingRecordSyncQueue';

export class RecordSyncQueueError extends Error {
  readonly code: 'invalid_queue' | 'unsupported_queue_version' | 'version_conflict' | 'payload_conflict' | 'mixed_queue_versions' | 'storage_coordination_unavailable' | 'target_unverified' | 'target_mismatch';
  constructor(code: RecordSyncQueueError['code'], message: string) {
    super(message);
    this.name = 'RecordSyncQueueError';
    this.code = code;
  }
}
type Storage = {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<unknown>;
  removeItem(key: string): Promise<unknown>;
};
export type RecordSyncQueueLock = <T>(work: () => Promise<T>) => Promise<T>;
type WebLockManager = {
  request<T>(name: string, options: { mode: 'exclusive' }, work: () => Promise<T>): Promise<T>;
};
export type RecordSyncQueueOptions = {
  legacyMealType(timestamp: string): MealType;
  now?: () => string;
  newId?: () => string;
  lock?: RecordSyncQueueLock;
};
type Options = RecordSyncQueueOptions;

/** Every cooperating tab uses one lock, including readers that may migrate data. */
export function createWebRecordSyncQueueLock(manager?: WebLockManager | null): RecordSyncQueueLock {
  return async <T>(work: () => Promise<T>): Promise<T> => {
    if (!manager || typeof manager.request !== 'function') {
      throw new RecordSyncQueueError('storage_coordination_unavailable', 'Web queue coordination is unavailable; stored data has not been changed');
    }
    let entered = false;
    try {
      return await manager.request(RECORD_SYNC_QUEUE_LOCK_NAME, { mode: 'exclusive' }, async () => {
        entered = true;
        return work();
      });
    } catch (error) {
      if (entered) throw error;
      throw new RecordSyncQueueError('storage_coordination_unavailable', 'Could not acquire web queue coordination; stored data has not been changed');
    }
  };
}
function fail(message: string): never {
  throw new RecordSyncQueueError('invalid_queue', message);
}
function jsonCopy<T>(value: T): T {
  try {
    const json = JSON.stringify(value, function (_key, item) {
      if (typeof item === 'number' && !Number.isFinite(item)) fail('Queue numbers must be finite');
      if (typeof item === 'undefined' && !Array.isArray(this)) return undefined;
      if (typeof item === 'undefined' || typeof item === 'function' || typeof item === 'symbol' || typeof item === 'bigint') {
        fail('Queue snapshots must contain JSON values');
      }
      return item;
    });
    return JSON.parse(json);
  } catch (error) {
    if (error instanceof RecordSyncQueueError) throw error;
    return fail('Queue snapshot is not valid JSON');
  }
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail('Queue entry must be an object');
  return value as Record<string, unknown>;
}
function text(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}
function timestamp(value: unknown): value is string {
  return text(value) && /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) && Number.isFinite(Date.parse(value));
}
function backendTarget(value: unknown): value is string {
  if (!text(value) || /[\u0000-\u0020\u007f]/.test(value)) return false;
  try {
    const url = new URL(value);
    return (url.protocol === 'http:' || url.protocol === 'https:') && Boolean(url.hostname)
      && !url.username && !url.password;
  } catch { return false; }
}
function source(value: unknown): value is RecordSource {
  return value === 'camera' || value === 'manual' || value === 'nutrition-label';
}
function mealType(value: unknown): value is MealType {
  return value === '早餐' || value === '午餐' || value === '晚餐' || value === '點心';
}
function validateV2Foods(foods: unknown[]) {
  if (!foods.length || foods.length > 200) fail('Queue create payload requires 1 to 200 foods');
  const allowed = new Set(['item_id', 'name', 'weight_g', 'portion_source', 'included', 'exclusion_reason', 'food_key', 'user_entered_nutrients', 'is_fried']);
  const portionSources = new Set(['unknown', 'vision_estimate', 'user_adjusted', 'user_weighed', 'label_weight', 'assumed']);
  const ids = new Set<string>();
  for (const raw of foods) {
    const food = object(raw);
    if (Object.keys(food).some((key) => !allowed.has(key))) fail('Queue create payload cannot upload source snapshots or unknown food fields');
    if (!text(food.item_id) || !text(food.name) || ids.has(food.item_id)) fail('Queue food identities must be present and unique');
    ids.add(food.item_id);
    if (food.weight_g !== null && (typeof food.weight_g !== 'number' || !Number.isFinite(food.weight_g) || food.weight_g <= 0)) fail('Queue food weight is invalid');
    if (typeof food.portion_source !== 'string' || !portionSources.has(food.portion_source)) fail('Queue food portion source is invalid');
    if (food.included !== undefined && typeof food.included !== 'boolean') fail('Queue food inclusion is invalid');
    if (food.included === false ? food.exclusion_reason !== 'not_consumed' : food.exclusion_reason != null) fail('Queue food exclusion is invalid');
    if ('food_key' in food && (!text(food.food_key) || 'user_entered_nutrients' in food)) fail('Queue food lookup and manual nutrients are mutually exclusive');
    if ('is_fried' in food && (typeof food.is_fried !== 'boolean' || !('user_entered_nutrients' in food))) fail('Queue manual fried-food setting is invalid');
    if ('user_entered_nutrients' in food) {
      const nutrients = object(food.user_entered_nutrients);
      const fields = ['calories', 'protein', 'carbs', 'sugar', 'fat', 'saturated_fat', 'trans_fat', 'sodium', 'fiber'];
      if (Object.keys(nutrients).length !== fields.length || fields.some((key) => !(key in nutrients))) fail('Queue manual nutrients require all nine nullable fields');
    }
  }
}
function normalizeEntry(value: unknown, options: Options, legacy = false): VersionedPendingRecordSync {
  const entry = object(value);
  if (!text(entry.id) || !text(entry.userId) || !source(entry.source)) fail('Queue identity or source is invalid');
  if (!timestamp(entry.createdAt) || !timestamp(entry.updatedAt)) fail('Queue timestamps must include a timezone');
  const version = legacy ? (entry.nutritionContractVersion ?? 1) : entry.nutritionContractVersion;
  if (version !== 1 && version !== 2) {
    throw new RecordSyncQueueError('unsupported_queue_version', 'Unsupported nutrition version in queue');
  }
  if (legacy && version !== 1) fail('Unversioned queue cannot contain v2 records');
  const clientRecordId = legacy ? (entry.clientRecordId ?? entry.id) : entry.clientRecordId;
  if (!text(clientRecordId)) fail('Queue client record ID is invalid');
  const attempts = legacy ? (entry.attempts ?? 0) : entry.attempts;
  if (typeof attempts !== 'number' || !Number.isSafeInteger(attempts) || attempts < 0) fail('Queue attempts are invalid');
  const recordTimestamp = legacy ? (entry.recordTimestamp ?? entry.createdAt) : entry.recordTimestamp;
  if (!timestamp(recordTimestamp)) fail('Record timestamp must include a timezone');
  const selectedMealType = legacy ? (entry.mealType ?? options.legacyMealType(recordTimestamp)) : entry.mealType;
  if (!mealType(selectedMealType)) fail('Record meal type is invalid');
  const error = entry.error ?? (legacy ? '後端暫時無法儲存這筆紀錄' : undefined);
  if (typeof error !== 'string') fail('Queue error must be text');
  if (entry.apiBaseUrl !== undefined && !backendTarget(entry.apiBaseUrl)) fail('Queue backend target must be an HTTP(S) URL without credentials');
  const base = {
    id: entry.id, userId: entry.userId, clientRecordId, source: entry.source,
    error, attempts, createdAt: entry.createdAt, updatedAt: entry.updatedAt,
    recordTimestamp, mealType: selectedMealType, ...(entry.apiBaseUrl === undefined ? {} : { apiBaseUrl: entry.apiBaseUrl }),
  };
  if (version === 1) {
    if (!Array.isArray(entry.foods) || 'payload' in entry) fail('Legacy queue requires detected foods');
    return jsonCopy({ ...base, nutritionContractVersion: 1, foods: entry.foods }) as PendingRecordSync;
  }
  const payload = object(entry.payload);
  if (payload.nutrition_contract_version !== 2 || payload.user_id !== base.userId
      || payload.client_record_id !== base.clientRecordId || payload.timestamp !== base.recordTimestamp
      || payload.meal_type !== base.mealType || payload.source !== base.source || !Array.isArray(payload.foods)
      || 'foods' in entry) {
    fail('V2 queue payload disagrees with its identity or original record time');
  }
  const allowedPayload = new Set(['nutrition_contract_version', 'user_id', 'client_record_id', 'timestamp', 'meal_type', 'source', 'foods', 'nutrition_context']);
  if (Object.keys(payload).some((key) => !allowedPayload.has(key))) fail('Queue create payload contains unsupported fields');
  if ('nutrition_context' in payload) {
    const context = object(payload.nutrition_context);
    if (Object.keys(context).some((key) => key !== 'scan_id' && key !== 'recognition_context')
        || ('scan_id' in context && !text(context.scan_id))) fail('Queue create payload cannot upload computed nutrition context');
    if ('recognition_context' in context) object(context.recognition_context);
  }
  validateV2Foods(payload.foods);
  return jsonCopy({ ...base, nutritionContractVersion: 2, payload }) as PendingV2RecordSync;
}
function validateEntries(entries: unknown[], options: Options, legacy = false): VersionedPendingRecordSync[] {
  const normalized = entries.map((entry) => normalizeEntry(entry, options, legacy));
  const ids = new Set<string>();
  const clientIds = new Set<string>();
  for (const entry of normalized) {
    const key = JSON.stringify([entry.userId, entry.clientRecordId]);
    if (ids.has(entry.id) || clientIds.has(key)) fail('Duplicate identity in queue');
    ids.add(entry.id);
    clientIds.add(key);
  }
  return normalized;
}
export function parseRecordSyncQueue(raw: string, options: Options, legacy = false): RecordSyncQueueEnvelope {
  let parsed: unknown;
  try { parsed = JSON.parse(raw); } catch { return fail('Stored queue is not valid JSON'); }
  if (legacy) {
    if (!Array.isArray(parsed)) fail('Legacy queue must be an array');
    return { queue_schema_version: 2, entries: validateEntries(parsed, options, true) };
  }
  const envelope = object(parsed);
  if (envelope.queue_schema_version !== 2) {
    throw new RecordSyncQueueError('unsupported_queue_version', 'Unsupported queue schema version');
  }
  if (!Array.isArray(envelope.entries)) fail('Queue entries must be an array');
  return { queue_schema_version: 2, entries: validateEntries(envelope.entries, options) };
}
function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson((value as Record<string, unknown>)[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}
export function canRetryPendingRecordSync(item: Pick<PendingSyncBase, 'attempts'>): boolean {
  return Number.isSafeInteger(item.attempts) && item.attempts >= 0 && item.attempts < MAX_RECORD_SYNC_ATTEMPTS;
}
export function getPendingRecordReplayMetadata(item: Pick<PendingSyncBase, 'recordTimestamp' | 'mealType'>) {
  if (!timestamp(item.recordTimestamp) || !mealType(item.mealType)) fail('Queued record replay metadata is invalid');
  return { timestamp: item.recordTimestamp, mealType: item.mealType };
}
export function assertPendingRecordSyncTarget(item: Pick<PendingSyncBase, 'apiBaseUrl'>, apiBaseUrl: string): void {
  if (!backendTarget(item.apiBaseUrl) || !backendTarget(apiBaseUrl)) {
    throw new RecordSyncQueueError('target_unverified', 'Queued record backend target cannot be verified; stored data has not been changed');
  }
  if (item.apiBaseUrl !== apiBaseUrl) {
    throw new RecordSyncQueueError('target_mismatch', 'Queued record belongs to a different backend; stored data has not been changed');
  }
}

/** Native uses this runtime's mutex; web also injects an exclusive cross-tab lock. */
export function createRecordSyncQueueStore(storage: Storage, options: Options) {
  let tail: Promise<unknown> = Promise.resolve();
  const now = options.now ?? (() => new Date().toISOString());
  const newId = options.newId ?? (() => `pending_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`);
  function locked<T>(work: () => Promise<T>): Promise<T> {
    const result = tail.then(() => options.lock ? options.lock(work) : work());
    tail = result.catch(() => undefined);
    return result;
  }
  async function read(): Promise<VersionedPendingRecordSync[]> {
    const current = await storage.getItem(RECORD_SYNC_QUEUE_KEY);
    const old = await storage.getItem(LEGACY_RECORD_SYNC_QUEUE_KEY);
    if (current !== null) {
      const envelope = parseRecordSyncQueue(current, options);
      if (old !== null) {
        throw new RecordSyncQueueError('mixed_queue_versions', 'Both legacy and current queues exist; preserve both snapshots for reconciliation');
      }
      return envelope.entries;
    }
    if (old === null) return [];
    const envelope = parseRecordSyncQueue(old, options, true);
    if (await storage.getItem(RECORD_SYNC_QUEUE_KEY) !== null) {
      throw new RecordSyncQueueError('mixed_queue_versions', 'Queue changed while migrating; preserve both snapshots');
    }
    await storage.setItem(RECORD_SYNC_QUEUE_KEY, JSON.stringify(envelope));
    if (await storage.getItem(LEGACY_RECORD_SYNC_QUEUE_KEY) !== old) {
      throw new RecordSyncQueueError('mixed_queue_versions', 'Legacy queue changed while migrating; preserve both snapshots');
    }
    await storage.removeItem(LEGACY_RECORD_SYNC_QUEUE_KEY);
    return envelope.entries;
  }
  async function write(entries: VersionedPendingRecordSync[]) {
    const validated = validateEntries(jsonCopy(entries), options);
    await storage.setItem(RECORD_SYNC_QUEUE_KEY, JSON.stringify({ queue_schema_version: 2, entries: validated }));
    return jsonCopy(validated);
  }
  const legacyOnly = (entries: VersionedPendingRecordSync[]) => entries.filter((entry): entry is PendingRecordSync => entry.nutritionContractVersion === 1);
  async function enqueue(candidate: VersionedPendingRecordSync, existingEntries?: VersionedPendingRecordSync[]): Promise<VersionedPendingRecordSync[]> {
    const entries = existingEntries ?? await read();
    const existing = entries.find((entry) => entry.userId === candidate.userId && entry.clientRecordId === candidate.clientRecordId);
    if (existing) {
      if (existing.nutritionContractVersion !== candidate.nutritionContractVersion) {
        throw new RecordSyncQueueError('version_conflict', 'Cannot change the nutrition version of a queued record');
      }
      const before = existing.nutritionContractVersion === 2 ? existing.payload : existing.foods;
      const after = candidate.nutritionContractVersion === 2 ? candidate.payload : candidate.foods;
      if (stableJson(before) !== stableJson(after) || existing.source !== candidate.source
          || existing.recordTimestamp !== candidate.recordTimestamp || existing.mealType !== candidate.mealType
          || existing.apiBaseUrl !== candidate.apiBaseUrl) {
        throw new RecordSyncQueueError('payload_conflict', 'Queued record snapshot cannot change under the same client record ID');
      }
      return write(entries.map((entry) => entry.id === existing.id
        ? { ...entry, error: candidate.error, updatedAt: candidate.updatedAt } : entry));
    }
    return write([...entries, candidate]);
  }
  return {
    loadAll: () => locked(async () => jsonCopy(await read())),
    loadLegacy: () => locked(async () => legacyOnly(await read())),
    saveLegacy: (entries: PendingRecordSync[]) => {
      const snapshot = jsonCopy(entries);
      return locked(async () => {
        const all = await read();
        if (snapshot.some((entry) => entry.nutritionContractVersion !== 1)) {
          throw new RecordSyncQueueError('version_conflict', 'Legacy queue writer cannot write v2 entries');
        }
        const preserved = all.filter((entry) => entry.nutritionContractVersion === 2);
        await write([...preserved, ...snapshot]);
      });
    },
    enqueueLegacy: (params: { userId: string; clientRecordId: string; foods: DetectedFood[]; source: RecordSource; error: string; recordTimestamp?: string; mealType?: MealType; apiBaseUrl?: string }) => {
      const snapshot = jsonCopy(params);
      if (snapshot.apiBaseUrl !== undefined && !backendTarget(snapshot.apiBaseUrl)) fail('Queue backend target must be an HTTP(S) URL without credentials');
      return locked(async () => {
        const at = now();
        const entries = await read();
        const existing = entries.find((entry) => entry.userId === snapshot.userId && entry.clientRecordId === snapshot.clientRecordId);
        const recordTimestamp = snapshot.recordTimestamp ?? existing?.recordTimestamp ?? at;
        const candidate = normalizeEntry({ ...snapshot, id: newId(), attempts: 0, createdAt: at, updatedAt: at,
          apiBaseUrl: snapshot.apiBaseUrl ?? existing?.apiBaseUrl,
          nutritionContractVersion: 1, recordTimestamp, mealType: snapshot.mealType ?? existing?.mealType ?? options.legacyMealType(recordTimestamp) }, options);
        return legacyOnly(await enqueue(candidate, entries));
      });
    },
    enqueueV2: (payload: QueuedNutritionRecordCreateV2, error: string, apiBaseUrl?: string) => {
      const snapshot = jsonCopy(payload);
      if (apiBaseUrl !== undefined && !backendTarget(apiBaseUrl)) fail('Queue backend target must be an HTTP(S) URL without credentials');
      return locked(async () => {
        const at = now();
        const entries = await read();
        const existing = entries.find((entry) => entry.userId === snapshot.user_id && entry.clientRecordId === snapshot.client_record_id);
        const candidate = normalizeEntry({ id: newId(), userId: snapshot.user_id, clientRecordId: snapshot.client_record_id,
          apiBaseUrl: apiBaseUrl ?? existing?.apiBaseUrl,
          source: snapshot.source, error, attempts: 0, createdAt: at, updatedAt: at,
          nutritionContractVersion: 2, recordTimestamp: snapshot.timestamp, mealType: snapshot.meal_type, payload: snapshot }, options);
        return enqueue(candidate, entries);
      });
    },
    removeLegacy: (id: string) => locked(async () => legacyOnly(await write((await read()).filter((entry) => entry.nutritionContractVersion !== 1 || entry.id !== id)))),
    removeLegacyByClientId: (userId: string, clientRecordId: string) => locked(async () => legacyOnly(await write((await read()).filter((entry) => entry.nutritionContractVersion !== 1 || entry.userId !== userId || entry.clientRecordId !== clientRecordId)))),
    failLegacy: (id: string, error: string) => locked(async () => legacyOnly(await write((await read()).map((entry) => entry.nutritionContractVersion === 1 && entry.id === id
      ? { ...entry, error, attempts: entry.attempts + 1, updatedAt: now() } : entry)))),
    removeV2: (id: string) => locked(async () => write((await read()).filter((entry) => entry.nutritionContractVersion !== 2 || entry.id !== id))),
    failV2: (id: string, error: string) => locked(async () => write((await read()).map((entry) => entry.nutritionContractVersion === 2 && entry.id === id
      ? { ...entry, error, attempts: entry.attempts + 1, updatedAt: now() } : entry))),
  };
}
