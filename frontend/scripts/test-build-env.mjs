import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { exposeFrontendBuildEnvironment } = require('./with-google-map-env.js');

test('backend-style variables are exposed to the Expo static build', () => {
  const env = {
    RENDER: 'true',
    SUPABASE_URL: 'https://project.supabase.co',
    SUPABASE_PUBLISHABLE_KEY: 'publishable-key',
    GOOGLE_PLACES_API_KEY: 'places-key',
  };

  exposeFrontendBuildEnvironment(env);

  assert.equal(env.EXPO_PUBLIC_SUPABASE_URL, env.SUPABASE_URL);
  assert.equal(env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY, env.SUPABASE_PUBLISHABLE_KEY);
  assert.equal(env.EXPO_PUBLIC_SUPABASE_AUTH_REQUIRED, 'true');
  assert.equal(env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY, env.GOOGLE_PLACES_API_KEY);
});

test('explicit Expo public variables are not overwritten', () => {
  const env = {
    RENDER: 'true',
    SUPABASE_URL: 'https://shared.supabase.co',
    EXPO_PUBLIC_SUPABASE_URL: 'https://explicit.supabase.co',
    EXPO_PUBLIC_SUPABASE_AUTH_REQUIRED: 'false',
  };

  exposeFrontendBuildEnvironment(env);

  assert.equal(env.EXPO_PUBLIC_SUPABASE_URL, 'https://explicit.supabase.co');
  assert.equal(env.EXPO_PUBLIC_SUPABASE_AUTH_REQUIRED, 'false');
});

test('Render enables Auth even when Supabase credentials are missing', () => {
  const env = { RENDER: 'true' };

  exposeFrontendBuildEnvironment(env);

  assert.equal(env.EXPO_PUBLIC_SUPABASE_AUTH_REQUIRED, 'true');
  assert.equal(env.EXPO_PUBLIC_SUPABASE_URL, undefined);
  assert.equal(env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY, undefined);
});
