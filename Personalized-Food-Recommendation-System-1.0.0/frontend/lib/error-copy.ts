/**
 * 把網路層丟出來的英文原文換成使用者看得懂的一句話。
 *
 * `fetch` 連不上時瀏覽器只會給 "Failed to fetch"——沒有主機、沒有原因，
 * 而「我的」頁先前把它原樣接在「同步失敗：」後面貼上畫面。使用者看到的是
 * 一句英文，也不知道該不該重試。AuthGate 已經有一份等價的對照
 * （describeAuthError），那份只處理登入，這裡處理資料同步。
 */
export function describeRequestError(error: unknown, fallback = '儲存失敗'): string {
  const raw = String((error as { message?: string })?.message || '').trim();
  if (!raw) return fallback;

  const lower = raw.toLowerCase();
  if (lower.includes('failed to fetch') || lower.includes('networkerror') || lower.includes('network request failed')) {
    return '連不到伺服器，請確認網路連線後再試一次。';
  }
  if (lower.includes('timeout') || lower.includes('timed out')) {
    return '伺服器回應逾時，請稍後再試一次。';
  }
  if (raw.includes('登入') || raw.includes('session')) return raw;
  if (lower.includes('401') || lower.includes('unauthorized')) {
    return '登入狀態已過期，請重新登入後再試。';
  }

  // 後端自己回的訊息已經是中文，照原樣顯示。
  return raw;
}
