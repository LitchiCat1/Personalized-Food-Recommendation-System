import type { DetectedFood } from '@/constants/mock-data';
import type { MealType } from './meal';
import type { RecordSource } from './record-sync-contract';

export type RecordSubmission = {
  apiBaseUrl: string;
  userId: string;
  clientRecordId: string;
  foods: DetectedFood[];
  source: RecordSource;
  timestamp: string;
  mealType: MealType;
};

export class RecordSubmissionError extends Error {
  readonly code: 'submission_changed' | 'submission_interrupted';
  constructor(code: RecordSubmissionError['code']) {
    super(code === 'submission_changed'
      ? '這次送出的原內容已保留，請先同步原紀錄；修改後的內容請另建紀錄。'
      : '登入狀態已變更，本機原紀錄已保留。');
    this.name = 'RecordSubmissionError';
    this.code = code;
  }
}

function copy<T>(value: T): T {
  return JSON.parse(JSON.stringify(value, (_key, item) => {
    if (typeof item === 'number' && !Number.isFinite(item)) throw new Error('Invalid record number');
    return item;
  }));
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson((value as Record<string, unknown>)[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

type Entry = { request: RecordSubmission; saved: boolean };
type PrepareParams = Pick<RecordSubmission, 'apiBaseUrl' | 'userId' | 'foods' | 'source'> & { submissionKey: string };

/** Keeps one immutable event per visible draft, including ambiguous network failures. */
export function createRecordSubmissionSession(options: {
  now?: () => Date;
  newId?: () => string;
  mealType: (at: Date) => MealType;
  timestamp: (at: Date) => string;
}) {
  const entries = new Map<string, Entry>();
  const keyOf = (params: Pick<PrepareParams, 'apiBaseUrl' | 'userId' | 'submissionKey'>) =>
    JSON.stringify([params.apiBaseUrl, params.userId, params.submissionKey]);
  const contentOf = (params: Pick<PrepareParams, 'foods' | 'source'>) => stableJson({ foods: params.foods, source: params.source });

  function entryFor(request: RecordSubmission): Entry {
    const entry = [...entries.values()].find((item) => item.request.apiBaseUrl === request.apiBaseUrl
      && item.request.userId === request.userId && item.request.clientRecordId === request.clientRecordId);
    if (!entry || stableJson(entry.request) !== stableJson(request)) throw new RecordSubmissionError('submission_changed');
    return entry;
  }

  return {
    prepare(params: PrepareParams): RecordSubmission {
      const snapshot = copy(params);
      const key = keyOf(snapshot);
      const existing = entries.get(key);
      if (existing) {
        if (contentOf(existing.request) !== contentOf(snapshot)) throw new RecordSubmissionError('submission_changed');
        return copy(existing.request);
      }
      const at = options.now?.() ?? new Date();
      const request: RecordSubmission = {
        apiBaseUrl: snapshot.apiBaseUrl, userId: snapshot.userId, foods: snapshot.foods, source: snapshot.source,
        clientRecordId: options.newId?.() ?? `record_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`,
        timestamp: options.timestamp(at), mealType: options.mealType(at),
      };
      entries.set(key, { request, saved: false });
      return copy(request);
    },
    markSaved(apiBaseUrl: string, userId: string, clientRecordId: string) {
      for (const entry of entries.values()) {
        if (entry.request.apiBaseUrl === apiBaseUrl && entry.request.userId === userId
          && entry.request.clientRecordId === clientRecordId) entry.saved = true;
      }
    },
    async deliver(request: RecordSubmission, io: {
      persist: (request: RecordSubmission) => Promise<unknown>;
      send: (request: RecordSubmission) => Promise<unknown>;
      remove: (request: RecordSubmission) => Promise<unknown>;
      isCurrent: () => boolean;
    }): Promise<{ alreadySaved: boolean; cleanupPending: boolean }> {
      const entry = entryFor(request);
      const alreadySaved = entry.saved;
      if (!entry.saved) {
        await io.persist(copy(entry.request));
        if (!io.isCurrent()) throw new RecordSubmissionError('submission_interrupted');
        await io.send(copy(entry.request));
        entry.saved = true;
      }
      // A failed local cleanup must never turn a successful remote save into another event.
      try {
        await io.remove(copy(entry.request));
        return { alreadySaved, cleanupPending: false };
      } catch {
        return { alreadySaved, cleanupPending: true };
      }
    },
  };
}
