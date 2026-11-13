import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';
import { getAutoMealType } from '@/lib/meal';
import { createRecordSyncQueueStore, createWebRecordSyncQueueLock } from '@/lib/record-sync-contract';

export {
  MAX_RECORD_SYNC_ATTEMPTS,
  RecordSyncQueueError,
  canRetryPendingRecordSync,
  getPendingRecordReplayMetadata,
  assertPendingRecordSyncTarget,
} from '@/lib/record-sync-contract';
export type {
  PendingRecordSync,
  PendingV2RecordSync,
  VersionedPendingRecordSync,
  QueuedNutritionRecordCreateV2,
  RecordSource,
} from '@/lib/record-sync-contract';

const storage = Platform.OS === 'web'
  ? {
      async getItem(key: string) {
        return typeof window === 'undefined' ? null : window.localStorage.getItem(key);
      },
      async setItem(key: string, value: string) {
        if (typeof window === 'undefined') throw new Error('Record queue storage is unavailable');
        window.localStorage.setItem(key, value);
      },
      async removeItem(key: string) {
        if (typeof window === 'undefined') throw new Error('Record queue storage is unavailable');
        window.localStorage.removeItem(key);
      },
    }
  : AsyncStorage;

const queue = createRecordSyncQueueStore(storage, {
  legacyMealType: (timestamp) => getAutoMealType(new Date(timestamp)),
  lock: Platform.OS === 'web'
    ? createWebRecordSyncQueueLock(typeof navigator === 'undefined' ? null : navigator.locks)
    : undefined,
});

export const loadPendingRecordSyncQueue = queue.loadLegacy;
export const loadVersionedRecordSyncQueue = queue.loadAll;
export const savePendingRecordSyncQueue = queue.saveLegacy;
export const enqueuePendingRecordSync = queue.enqueueLegacy;
export const enqueuePendingV2RecordSync = queue.enqueueV2;
export const removePendingRecordSync = queue.removeLegacy;
export const removePendingRecordSyncByClientRecordId = queue.removeLegacyByClientId;
export const markPendingRecordSyncFailed = queue.failLegacy;
export const removePendingV2RecordSync = queue.removeV2;
export const markPendingV2RecordSyncFailed = queue.failV2;
