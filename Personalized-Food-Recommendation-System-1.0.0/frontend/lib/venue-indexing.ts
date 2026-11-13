import type { VenueIndexSummary } from '@/lib/api';

/**
 * 「建立附近店家菜單檔案」按一次就做完。
 *
 * 後端一次請求只花 75 秒分析菜單，做不完的回報在 remaining。先前要使用者
 * 看到「還有 18 家沒建（再按一次繼續）」自己一直按；這裡在「這一輪有進度」
 * 時自動再送，一輪都沒建出來就停下來說明原因，免得空轉。
 * 每一輪都用同一組座標，後端的店家搜尋有 10 分鐘快取，不會每輪都多一次
 * Places 計費；輪數上限是為了不讓使用者一直等下去（一輪最多約 105 秒）。
 */
export const MAX_INDEX_ROUNDS = 5;

export type VenueIndexProgress = { built: number; target: number; round: number };

export type VenueIndexRun = {
  rounds: number;
  /** 這次（所有輪加起來）新建的店家數 */
  builtNow: number;
  /** 最後一輪的結果；一輪都沒跑完時是 null */
  last: VenueIndexSummary | null;
  stopReason: 'done' | 'no-progress' | 'round-limit' | 'error';
  error?: string;
};

/** 現在有菜單可用的店家。舊版後端沒有 with_menu，就用已建檔加這次建的估。 */
function builtSoFar(summary: VenueIndexSummary): number {
  return summary.with_menu ?? summary.already_cached + summary.analysed;
}

/** 能建出菜單的店家：扣掉沒有店名、問不出菜單、還在冷卻中的。 */
function buildableCount(summary: VenueIndexSummary): number {
  return summary.found - (summary.unbuildable ?? 0);
}

export function describeIndexProgress(progress: VenueIndexProgress | null): string {
  if (!progress) return '建檔中…';
  return `建檔中… 已建 ${progress.built}／${progress.target} 家`;
}

export async function indexVenuesUntilDone(
  requestRound: () => Promise<VenueIndexSummary>,
  onProgress?: (progress: VenueIndexProgress) => void,
  maxRounds: number = MAX_INDEX_ROUNDS
): Promise<VenueIndexRun> {
  let last: VenueIndexSummary | null = null;
  let builtNow = 0;
  let rounds = 0;
  while (rounds < maxRounds) {
    let summary: VenueIndexSummary;
    try {
      summary = await requestRound();
    } catch (err: any) {
      // 第一輪就失敗，照原本的方式整個報錯；做到一半才停，已建的要講清楚
      if (!last) throw err;
      return { rounds, builtNow, last, stopReason: 'error', error: err?.message || String(err) };
    }
    rounds += 1;
    last = summary;
    builtNow += summary.analysed;
    onProgress?.({ built: builtSoFar(summary), target: buildableCount(summary), round: rounds });
    if (!summary.remaining) {
      return { rounds, builtNow, last, stopReason: 'done' };
    }
    if (summary.analysed <= 0) {
      return { rounds, builtNow, last, stopReason: 'no-progress' };
    }
  }
  return { rounds, builtNow, last, stopReason: 'round-limit' };
}

export type VenueIndexReport = {
  tone: 'success' | 'error';
  title: string;
  message: string;
};

function describeStall(last: VenueIndexSummary): string {
  if (last.in_progress) {
    return `另一個建檔正在處理其中 ${last.in_progress} 家，還有 ${last.remaining} 家沒建完，稍後再按一次看結果。`;
  }
  if (last.rate_limited) {
    return `Gemini 額度暫時用完，還有 ${last.remaining} 家沒建，請過幾分鐘再按一次。`;
  }
  return `這一輪沒有建出任何一家（Gemini 可能回應太慢），還有 ${last.remaining} 家沒建，請稍後再按一次。`;
}

/** 把整次建檔的結果寫成一則提示。extra 會接在說明最後（例如定位來源）。 */
export function describeIndexRun(run: VenueIndexRun, extra?: string): VenueIndexReport {
  const last = run.last;
  if (!last) {
    return { tone: 'error', title: '建立菜單檔案失敗', message: run.error || '沒有拿到建檔結果。' };
  }
  const built = builtSoFar(last);
  const notes: string[] = [];

  const unresolved = last.failed + (last.cooling_down ?? 0);
  if (unresolved > 0) {
    notes.push(`${unresolved} 家問不出菜單，先跳過（稍後再按會重試）。`);
  }
  if (last.remaining > 0) {
    if (run.stopReason === 'no-progress') {
      notes.push(describeStall(last));
    } else if (run.stopReason === 'round-limit') {
      notes.push(`已連續建檔 ${run.rounds} 輪，還有 ${last.remaining} 家沒建，可以再按一次繼續。`);
    } else if (run.stopReason === 'error') {
      notes.push(`建到一半停住了（${run.error}），還有 ${last.remaining} 家沒建，可以再按一次繼續。`);
    }
  }
  if (extra) notes.push(extra);

  // 這次一家都沒建成、又還沒做完，不能用綠色的「成功」讓人以為好了
  const succeeded = run.builtNow > 0 || (run.stopReason === 'done' && built > 0);
  return {
    tone: succeeded ? 'success' : 'error',
    title: `附近 ${last.found} 家店：已建檔 ${built} 家（這次新建 ${run.builtNow} 家）`,
    message: notes.join(''),
  };
}
