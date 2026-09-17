import assert from 'node:assert/strict';
import test from 'node:test';
import { describeIndexProgress, describeIndexRun, indexVenuesUntilDone, MAX_INDEX_ROUNDS } from '../lib/venue-indexing.ts';

function round(overrides) {
  return {
    message: '',
    found: 19,
    already_cached: 0,
    refreshed: 0,
    analysed: 0,
    failed: 0,
    cooling_down: 0,
    in_progress: 0,
    rate_limited: 0,
    remaining: 0,
    with_menu: 0,
    unbuildable: 0,
    total_cached: 0,
    ...overrides,
  };
}

function backend(rounds) {
  const queue = [...rounds];
  const api = async () => {
    api.calls += 1;
    const next = queue.shift();
    if (next instanceof Error) throw next;
    if (!next) throw new Error('多送了一輪');
    return next;
  };
  api.calls = 0;
  return api;
}

test('keeps asking while each round makes progress, and the progress reaches the end', async () => {
  // 台南安平那次：19 家，一輪只做得完幾家；最後 1 家問不出菜單
  const api = backend([
    round({ already_cached: 1, analysed: 6, with_menu: 7, remaining: 12 }),
    round({ already_cached: 7, analysed: 7, with_menu: 14, remaining: 5 }),
    round({ already_cached: 14, analysed: 4, failed: 1, with_menu: 18, unbuildable: 1, remaining: 0 }),
  ]);
  const progress = [];
  const run = await indexVenuesUntilDone(api, (p) => progress.push(describeIndexProgress(p)));

  assert.equal(api.calls, 3);
  assert.equal(run.stopReason, 'done');
  assert.equal(run.builtNow, 17);
  assert.deepEqual(progress, ['建檔中… 已建 7／19 家', '建檔中… 已建 14／19 家', '建檔中… 已建 18／18 家']);

  const report = describeIndexRun(run);
  assert.equal(report.tone, 'success');
  assert.equal(report.title, '附近 19 家店：已建檔 18 家（這次新建 17 家）');
  assert.match(report.message, /1 家問不出菜單，先跳過（稍後再按會重試）/);
  assert.doesNotMatch(report.message, /再按一次/);
});

test('a stale menu that failed to refresh still counts as built', async () => {
  const api = backend([round({ found: 3, already_cached: 1, refreshed: 1, failed: 1, with_menu: 2, unbuildable: 1 })]);
  const progress = [];
  await indexVenuesUntilDone(api, (p) => progress.push(p));
  assert.deepEqual(progress, [{ built: 2, target: 2, round: 1 }]);
});

test('an older backend without with_menu still gets a sensible count', async () => {
  const older = round({ already_cached: 3, analysed: 2, remaining: 0 });
  delete older.with_menu;
  delete older.unbuildable;
  const progress = [];
  await indexVenuesUntilDone(backend([older]), (p) => progress.push(p));
  assert.deepEqual(progress, [{ built: 5, target: 19, round: 1 }]);
});

test('stops, explains, and does not claim success when a round builds nothing', async () => {
  // 第一次按的實際結果：0 家建成、1 家失敗、17 家沒輪到
  const api = backend([round({ already_cached: 1, with_menu: 1, failed: 1, unbuildable: 1, remaining: 17 })]);
  const run = await indexVenuesUntilDone(api);

  assert.equal(api.calls, 1);
  assert.equal(run.stopReason, 'no-progress');
  const report = describeIndexRun(run);
  assert.equal(report.tone, 'error');
  assert.match(report.message, /這一輪沒有建出任何一家.*還有 17 家沒建/);
});

test('says the quota ran out when that is why nothing was built', async () => {
  const api = backend([
    round({ analysed: 5, with_menu: 5, remaining: 14 }),
    round({ already_cached: 5, with_menu: 5, rate_limited: 3, remaining: 14 }),
  ]);
  const run = await indexVenuesUntilDone(api);

  assert.equal(api.calls, 2);
  assert.equal(run.stopReason, 'no-progress');
  const report = describeIndexRun(run);
  assert.equal(report.tone, 'success');
  assert.match(report.message, /Gemini 額度暫時用完，還有 14 家沒建/);
});

test('says another run is handling the rest when that is why nothing was built', async () => {
  const api = backend([round({ already_cached: 4, with_menu: 4, in_progress: 15, remaining: 15 })]);
  const report = describeIndexRun(await indexVenuesUntilDone(api));
  assert.match(report.message, /另一個建檔正在處理其中 15 家/);
  assert.equal(report.tone, 'error');
});

test('gives up after the round limit even if progress continues', async () => {
  const rounds = Array.from({ length: MAX_INDEX_ROUNDS + 1 }, (_, i) =>
    round({ found: 20, already_cached: i, analysed: 1, with_menu: i + 1, remaining: 20 - i - 1 })
  );
  const api = backend(rounds);
  const run = await indexVenuesUntilDone(api);

  assert.equal(api.calls, MAX_INDEX_ROUNDS);
  assert.equal(run.stopReason, 'round-limit');
  assert.match(describeIndexRun(run).message, /已連續建檔 5 輪，還有 15 家沒建，可以再按一次繼續/);
});

test('venues already cooling down are reported but do not keep the loop going', async () => {
  const api = backend([round({ already_cached: 16, with_menu: 16, cooling_down: 3, unbuildable: 3, remaining: 0 })]);
  const run = await indexVenuesUntilDone(api);

  assert.equal(api.calls, 1);
  const report = describeIndexRun(run, '定位：台南。');
  assert.equal(report.tone, 'success');
  assert.equal(report.title, '附近 19 家店：已建檔 16 家（這次新建 0 家）');
  assert.equal(report.message, '3 家問不出菜單，先跳過（稍後再按會重試）。定位：台南。');
});

test('a first-round failure is thrown as before', async () => {
  const api = backend([new Error('店家搜尋失敗')]);
  await assert.rejects(indexVenuesUntilDone(api), /店家搜尋失敗/);
});

test('a failure after some progress keeps what was built and does not blame the network', async () => {
  const api = backend([
    round({ analysed: 6, with_menu: 6, remaining: 13 }),
    new Error('你的登入可能已過期，請重新登入後再試。'),
  ]);
  const run = await indexVenuesUntilDone(api);

  assert.equal(run.stopReason, 'error');
  assert.equal(run.builtNow, 6);
  const report = describeIndexRun(run);
  assert.equal(report.tone, 'success');
  assert.match(report.message, /建到一半停住了（你的登入可能已過期，請重新登入後再試。），還有 13 家沒建/);
  assert.doesNotMatch(report.message, /連線中斷/);
});

test('each round asks for the request again, so a refreshed token is picked up', async () => {
  const tokens = ['old-token', 'new-token'];
  const seen = [];
  const replies = [round({ analysed: 2, with_menu: 2, remaining: 3 }), round({ analysed: 3, with_menu: 5, remaining: 0 })];
  await indexVenuesUntilDone(async () => {
    seen.push(tokens[seen.length]);
    return replies.shift();
  });
  assert.deepEqual(seen, ['old-token', 'new-token']);
});

test('nothing built at all is shown as an error', async () => {
  const api = backend([round({ found: 2, failed: 2, unbuildable: 2, remaining: 0 })]);
  const report = describeIndexRun(await indexVenuesUntilDone(api));
  assert.equal(report.tone, 'error');
});

test('the button shows a plain label before the first round returns', () => {
  assert.equal(describeIndexProgress(null), '建檔中…');
});
