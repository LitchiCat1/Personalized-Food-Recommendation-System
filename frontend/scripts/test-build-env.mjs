import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { exposeFrontendBuildEnvironment } = require('./with-google-map-env.js');

test('backend-style variables are exposed to the Expo build', () => {
  const env = {
    AUTH_REQUIRED: 'false',
    GOOGLE_PLACES_API_KEY: 'places-key',
  };

  exposeFrontendBuildEnvironment(env);

  assert.equal(env.EXPO_PUBLIC_AUTH_REQUIRED, 'false');
  assert.equal(env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY, env.GOOGLE_PLACES_API_KEY);
});

test('explicit Expo public variables are not overwritten', () => {
  const env = {
    AUTH_REQUIRED: 'false',
    EXPO_PUBLIC_AUTH_REQUIRED: 'true',
  };

  exposeFrontendBuildEnvironment(env);

  assert.equal(env.EXPO_PUBLIC_AUTH_REQUIRED, 'true');
});

test('the key in backend/.env.local reaches the Expo build', () => {
  const env = {};

  exposeFrontendBuildEnvironment(env, {
    backendEnv: { GOOGLE_PLACES_API_KEY: 'local-places-key', AUTH_REQUIRED: 'true' },
  });

  assert.equal(env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY, 'local-places-key');
  assert.equal(env.EXPO_PUBLIC_AUTH_REQUIRED, 'true');
});

test('the shell environment wins over backend/.env.local', () => {
  const env = { GOOGLE_PLACES_API_KEY: 'shell-key' };

  exposeFrontendBuildEnvironment(env, {
    backendEnv: { GOOGLE_PLACES_API_KEY: 'local-places-key' },
  });

  assert.equal(env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY, 'shell-key');
});

test('a key set in frontend/.env.local is left for Expo to read', () => {
  const env = {};

  exposeFrontendBuildEnvironment(env, {
    frontendEnv: { EXPO_PUBLIC_GOOGLE_MAPS_API_KEY: 'browser-key' },
    backendEnv: { GOOGLE_PLACES_API_KEY: 'local-places-key' },
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
