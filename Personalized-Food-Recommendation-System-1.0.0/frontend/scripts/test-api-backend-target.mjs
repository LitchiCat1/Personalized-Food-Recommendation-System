import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const code = ts.transpileModule(fs.readFileSync(new URL('../lib/api.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;

function loadApi() {
  const module = { exports: {} };
  new Function('require', 'module', 'exports', code)((id) => {
    if (id === '@/lib/auth') return { reportUnauthorized() {} };
    throw new Error(`Unexpected runtime dependency: ${id}`);
  }, module, module.exports);
  return module.exports;
}

test('failed local recommendations keep auth and health checks on the selected backend', async (t) => {
  const previous = process.env.EXPO_PUBLIC_FALLBACK_API_BASE_URL;
  process.env.EXPO_PUBLIC_FALLBACK_API_BASE_URL = 'https://retired.example.invalid';
  t.after(() => {
    if (previous === undefined) delete process.env.EXPO_PUBLIC_FALLBACK_API_BASE_URL;
    else process.env.EXPO_PUBLIC_FALLBACK_API_BASE_URL = previous;
  });
  const api = loadApi();
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    calls.push({ url, init });
    if (url === 'http://127.0.0.1:5000/health') return new Response('', { status: 503 });
    throw new TypeError('Failed to fetch');
  });

  await assert.rejects(api.fetchHealthyFoodRecommendations(
    'http://127.0.0.1:5000', 'user/a', { lat: 25, lng: 121 }, { accessToken: 'test-session' },
  ), /無法連線到後端 API/);
  assert.deepEqual(calls.map((call) => call.url), [
    'http://127.0.0.1:5000/map-food-recommend/user%2Fa?lat=25&lng=121&radius_km=5&category=all',
    'http://127.0.0.1:5000/health',
  ]);
  assert.equal(calls[0].init.headers.Authorization, 'Bearer test-session');
  assert.equal(calls[1].init, undefined);
});

test('reachable health retains the recommendation failure diagnosis without another backend', async (t) => {
  const api = loadApi();
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url) => {
    calls.push(url);
    if (url.endsWith('/health')) return new Response('{}');
    throw new TypeError('Network request failed');
  });
  await assert.rejects(api.fetchHealthyFoodRecommendations(
    'http://localhost:5000', 'user-a', { lat: 25, lng: 121 }, { accessToken: 'test-session' },
  ), /後端健康檢查可連線/);
  assert.equal(calls.length, 2);
  assert.ok(calls.every((url) => new URL(url).origin === 'http://localhost:5000'));
});

test('successful recommendations use the configured HTTPS backend once', async (t) => {
  const api = loadApi();
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    calls.push({ url, init });
    return new Response(JSON.stringify({ restaurants: [] }));
  });
  assert.deepEqual(await api.fetchHealthyFoodRecommendations(
    'https://my-pc.tail1234.ts.net', 'user-a', { lat: 25, lng: 121 }, { accessToken: 'test-session' },
  ), { restaurants: [] });
  assert.equal(calls.length, 1);
  assert.equal(new URL(calls[0].url).origin, 'https://my-pc.tail1234.ts.net');
  assert.equal(calls[0].init.headers.Authorization, 'Bearer test-session');
});
