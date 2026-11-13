import assert from 'node:assert/strict';
import test from 'node:test';
import { getBrowserPosition } from '../lib/browser-location.ts';

const KEELUNG = { latitude: 25.1283, longitude: 121.7431 };
const JIUFEN = { latitude: 25.1092, longitude: 121.8445 };

/**
 * 模擬瀏覽器的 navigator.geolocation：跟真的瀏覽器一樣，
 * 上一次的位置還沒超過 maximumAge 就直接回傳舊的，不會重新定位。
 */
function fakeBrowser(startAt) {
  let current = startAt;
  let cached = null;
  let now = 0;
  const calls = [];
  return {
    calls,
    moveTo(coords) {
      current = coords;
    },
    wait(ms) {
      now += ms;
    },
    geolocation: {
      getCurrentPosition(success, _error, options = {}) {
        calls.push(options);
        // 規格：maximumAge 為 0 時一定要重新定位
        const maximumAge = options.maximumAge ?? 0;
        if (!cached || maximumAge <= 0 || now - cached.timestamp > maximumAge) {
          cached = { coords: { ...current }, timestamp: now };
        }
        success(cached);
      },
    },
  };
}

test('asks the browser for a fresh fix instead of its cached one', async () => {
  const browser = fakeBrowser(KEELUNG);
  await getBrowserPosition(browser.geolocation);
  // expo-location 網頁版帶的是 Infinity，瀏覽器就永遠回傳快取
  assert.equal(browser.calls[0].maximumAge, 0);
  assert.equal(browser.calls[0].enableHighAccuracy, false);
});

test('a traveler who keeps the page open gets the new location', async () => {
  // 網頁開著從基隆移動到九份，再按「更新地圖」，要拿到九份，不是基隆
  const browser = fakeBrowser(KEELUNG);
  const first = await getBrowserPosition(browser.geolocation);
  assert.deepEqual(first.coords, KEELUNG);

  browser.wait(30 * 60 * 1000);
  browser.moveTo(JIUFEN);
  const second = await getBrowserPosition(browser.geolocation);
  assert.deepEqual(second.coords, JIUFEN);
});

test('gets the new location even right after the previous fix', async () => {
  // 用 DevTools 改模擬位置後馬上按「更新地圖」，也要拿到新的位置
  const browser = fakeBrowser(KEELUNG);
  await getBrowserPosition(browser.geolocation);
  browser.moveTo(JIUFEN);
  const second = await getBrowserPosition(browser.geolocation);
  assert.deepEqual(second.coords, JIUFEN);
});

test('rejects when the browser cannot locate, so the caller can fall back', async () => {
  const denied = { code: 1, message: 'User denied Geolocation' };
  const geolocation = {
    getCurrentPosition(_success, error) {
      error(denied);
    },
  };
  await assert.rejects(getBrowserPosition(geolocation), (err) => err === denied);
});

test('rejects instead of throwing when the browser has no geolocation', async () => {
  // 不安全的網址或舊瀏覽器可能沒有 navigator.geolocation
  await assert.rejects(getBrowserPosition(undefined), TypeError);
});
