import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { exposeFrontendBuildEnvironment } = require('./with-google-map-env.js');

test('backend-style variables are exposed to the Expo build', () => {
  const env = {
    AUTH_REQUIRED: 'false',
    GOOGLE_MAPS_BROWSER_KEY: 'browser-key',
  };

  exposeFrontendBuildEnvironment(env);

  assert.equal(env.EXPO_PUBLIC_AUTH_REQUIRED, 'false');
  assert.equal(env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY, 'browser-key');
});

test('the server-side Places key never becomes a public build variable', () => {
  // EXPO_PUBLIC_* 會原樣寫進網站的 JS，任何開網站的人都讀得到。
  // 後端呼叫 Places（按次計費）的金鑰不能拿來當地圖的瀏覽器金鑰。
  for (const sources of [
    { env: { GOOGLE_PLACES_API_KEY: 'server-key' } },
    { env: { GOOGLE_MAPS_API_KEY: 'server-key' } },
    { env: {}, backendEnv: { GOOGLE_PLACES_API_KEY: 'server-key', GOOGLE_MAPS_API_KEY: 'server-key' } },
  ]) {
    const env = { ...sources.env };
    exposeFrontendBuildEnvironment(env, { backendEnv: sources.backendEnv || {} });
    assert.equal(env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY, undefined);
  }
});

test('explicit Expo public variables are not overwritten', () => {
  const env = {
    AUTH_REQUIRED: 'false',
    EXPO_PUBLIC_AUTH_REQUIRED: 'true',
  };

  exposeFrontendBuildEnvironment(env);

  assert.equal(env.EXPO_PUBLIC_AUTH_REQUIRED, 'true');
});

test('the browser key in backend/.env.local reaches the Expo build', () => {
  const env = {};

  exposeFrontendBuildEnvironment(env, {
    backendEnv: { GOOGLE_MAPS_BROWSER_KEY: 'local-browser-key', GOOGLE_PLACES_API_KEY: 'server-key', AUTH_REQUIRED: 'true' },
  });

  assert.equal(env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY, 'local-browser-key');
  assert.equal(env.EXPO_PUBLIC_AUTH_REQUIRED, 'true');
});

test('the shell environment wins over backend/.env.local', () => {
  const env = { GOOGLE_MAPS_BROWSER_KEY: 'shell-key' };

  exposeFrontendBuildEnvironment(env, {
    backendEnv: { GOOGLE_MAPS_BROWSER_KEY: 'local-browser-key' },
  });

  assert.equal(env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY, 'shell-key');
});

test('a key set in frontend/.env.local is left for Expo to read', () => {
  const env = {};

  exposeFrontendBuildEnvironment(env, {
    frontendEnv: { EXPO_PUBLIC_GOOGLE_MAPS_API_KEY: 'browser-key' },
    backendEnv: { GOOGLE_MAPS_BROWSER_KEY: 'local-browser-key' },
  });

  assert.equal(env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY, undefined);
});

test('nothing is invented when nothing is set', () => {
  const env = {};

  exposeFrontendBuildEnvironment(env);

  assert.equal(env.EXPO_PUBLIC_AUTH_REQUIRED, undefined);
  assert.equal(env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY, undefined);
});

test('build:local points the website at the backend that serves it', () => {
  const env = { EXPO_PUBLIC_API_BASE_URL: 'http://127.0.0.1:5000' };

  exposeFrontendBuildEnvironment(env, { sameOriginApi: true });

  assert.equal(env.EXPO_PUBLIC_API_BASE_URL, 'same-origin');
});
