type FdcFailure = { code?: unknown; status?: unknown };

const STALE_REFERENCE_CODES = new Set([
  'expired', 'revoked', 'superseded', 'stale_revision', 'scan_unavailable', 'scan_not_found',
  'snapshot_unavailable', 'snapshot_mismatch', 'snapshot_conflict', 'item_set_mismatch',
  'confirmation_conflict', 'wrong_confirmation', 'revision_conflict', 'authorization_changed',
  'preview_not_found', 'preview_unavailable', 'preview_conflict',
]);

export function getNutritionFdcRecovery(error: unknown): {
  rescan: boolean; retryable: boolean; message: string;
} {
  const failure: FdcFailure = error !== null && typeof error === 'object' ? error : {};
  const code = typeof failure.code === 'string' ? failure.code : '';
  if (STALE_REFERENCE_CODES.has(code)) {
    return {
      rescan: true, retryable: false,
      message: '這次掃描的候選或確認已過期或失效，請重新拍照或從相簿選擇餐點。原有辨識結果仍保留。',
    };
  }
  if (code === 'feature_disabled') {
    return { rescan: false, retryable: false, message: 'USDA 候選與營養預覽目前未啟用。' };
  }
  if (failure.status === 401 || failure.status === 403) {
    return { rescan: false, retryable: false, message: '目前無法驗證這次掃描的權限，請確認登入狀態後重新掃描。' };
  }
  if (failure.status === 429) {
    return { rescan: false, retryable: true, message: '查詢次數暫時達到上限，請稍後重試；掃描過期時需重新辨識。' };
  }
  if (code === 'network_error' || code === 'reservation_lost' || failure.status === 0 ||
      (typeof failure.status === 'number' && failure.status >= 500 && failure.status <= 599)) {
    return { rescan: false, retryable: true, message: '暫時無法取得 USDA 資料，請稍後重試。原有辨識結果與確認決定仍保留。' };
  }
  return { rescan: false, retryable: false, message: 'USDA 資料無法通過檢查，請重新辨識或使用手動搜尋。' };
}
