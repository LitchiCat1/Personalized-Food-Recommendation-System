import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';
import type { DetectedFood } from '@/constants/mock-data';


export type RecordSource = 'camera' | 'manual' | 'nutrition-label';

export type PendingRecordSync = {
  id: string;
  userId: string;
  clientRecordId: string;
  foods: DetectedFood[];
  source: RecordSource;
  error: string;
  attempts: number;
  createdAt: string;
  updatedAt: string;
};

export const MAX_RECORD_SYNC_ATTEMPTS = 5;

const QUEUE_KEY = 'nutrilens.pendingRecordSyncQueue.v1';

const storage = Platform.OS === 'web'
  ? {
      async getItem(key: string) {
        return typeof window === 'undefined' ? null : window.localStorage.getItem(key);
      },
      async setItem(key: string, value: string) {
        if (typeof window !== 'undefined') window.localStorage.setItem(key, value);
      },
      async removeItem(key: string) {
        if (typeof window !== 'undefined') window.localStorage.removeItem(key);
      },
    }
  : AsyncStorage;

export async function loadPendingRecordSyncQueue(): Promise<PendingRecordSync[]> {
  const raw = await storage.getItem(QUEUE_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map(normalizePendingRecordSync).filter(isPendingRecordSync) : [];
  } catch {
    await storage.removeItem(QUEUE_KEY);
    return [];
  }
}

export async function savePendingRecordSyncQueue(queue: PendingRecordSync[]): Promise<void> {
  await storage.setItem(QUEUE_KEY, JSON.stringify(queue));
}

export async function enqueuePendingRecordSync(params: {
  userId: string;
  clientRecordId: string;
  foods: DetectedFood[];
  source: RecordSource;
  error: string;
}): Promise<PendingRecordSync[]> {
  const queue = await loadPendingRecordSyncQueue();
  const now = new Date().toISOString();
  const existingIndex = queue.findIndex((item) => (
    item.userId === params.userId && item.clientRecordId === params.clientRecordId
  ));
  const nextQueue = [...queue];

  if (existingIndex >= 0) {
    nextQueue[existingIndex] = {
      ...nextQueue[existingIndex],
      foods: params.foods,
      source: params.source,
      error: params.error,
      updatedAt: now,
    };
  } else {
    nextQueue.push({
      id: `pending_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      userId: params.userId,
      clientRecordId: params.clientRecordId,
      foods: params.foods,
      source: params.source,
      error: params.error,
      attempts: 0,
      createdAt: now,
      updatedAt: now,
    });
  }

  await savePendingRecordSyncQueue(nextQueue);
  return nextQueue;
}

export async function removePendingRecordSync(id: string): Promise<PendingRecordSync[]> {
  const queue = await loadPendingRecordSyncQueue();
  const nextQueue = queue.filter((item) => item.id !== id);
  await savePendingRecordSyncQueue(nextQueue);
  return nextQueue;
}

export async function removePendingRecordSyncByClientRecordId(
  userId: string,
  clientRecordId: string
): Promise<PendingRecordSync[]> {
  const queue = await loadPendingRecordSyncQueue();
  const nextQueue = queue.filter((item) => (
    item.userId !== userId || item.clientRecordId !== clientRecordId
  ));
  await savePendingRecordSyncQueue(nextQueue);
  return nextQueue;
}

export async function markPendingRecordSyncFailed(id: string, error: string): Promise<PendingRecordSync[]> {
  const queue = await loadPendingRecordSyncQueue();
  const now = new Date().toISOString();
  const nextQueue = queue.map((item) => item.id === id
    ? { ...item, error, attempts: item.attempts + 1, updatedAt: now }
    : item);
  await savePendingRecordSyncQueue(nextQueue);
  return nextQueue;
}

export function canRetryPendingRecordSync(item: PendingRecordSync): boolean {
  return item.attempts < MAX_RECORD_SYNC_ATTEMPTS;
}

function normalizePendingRecordSync(value: any): PendingRecordSync | null {
  if (!value || typeof value.id !== 'string' || typeof value.userId !== 'string' || !Array.isArray(value.foods)) {
    return null;
  }
  if (value.source !== 'camera' && value.source !== 'manual' && value.source !== 'nutrition-label') {
    return null;
  }
  return {
    ...value,
    clientRecordId: typeof value.clientRecordId === 'string' ? value.clientRecordId : value.id,
    error: typeof value.error === 'string' ? value.error : '後端暫時無法儲存這筆紀錄',
    attempts: Math.max(0, Number(value.attempts || 0)),
    createdAt: typeof value.createdAt === 'string' ? value.createdAt : new Date().toISOString(),
    updatedAt: typeof value.updatedAt === 'string' ? value.updatedAt : new Date().toISOString(),
  };
}

function isPendingRecordSync(value: PendingRecordSync | null): value is PendingRecordSync {
  return value !== null;
}
