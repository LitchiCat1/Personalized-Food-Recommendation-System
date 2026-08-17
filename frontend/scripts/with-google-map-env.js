const { spawnSync } = require('node:child_process');

function exposeFrontendBuildEnvironment(env) {
  const mappings = [
    ['EXPO_PUBLIC_GOOGLE_MAPS_API_KEY', ['GOOGLE_PLACES_API_KEY', 'GOOGLE_MAPS_API_KEY']],
    ['EXPO_PUBLIC_SUPABASE_URL', ['SUPABASE_URL']],
    ['EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY', ['SUPABASE_PUBLISHABLE_KEY', 'SUPABASE_ANON_KEY']],
    ['EXPO_PUBLIC_SUPABASE_AUTH_REQUIRED', ['SUPABASE_AUTH_REQUIRED']],
  ];

  for (const [publicKey, sourceKeys] of mappings) {
    if (env[publicKey]) continue;
    const sourceValue = sourceKeys.map((key) => env[key]).find(Boolean);
    if (sourceValue) env[publicKey] = sourceValue;
  }

  if (!env.EXPO_PUBLIC_SUPABASE_AUTH_REQUIRED && String(env.RENDER || '').toLowerCase() === 'true') {
    env.EXPO_PUBLIC_SUPABASE_AUTH_REQUIRED = 'true';
  }

  return env;
}

function run() {
  const [, , ...args] = process.argv;

  if (args.length === 0) {
    console.error('Usage: node scripts/with-google-map-env.js <command> [args...]');
    process.exit(1);
  }

  exposeFrontendBuildEnvironment(process.env);

  const result = spawnSync(args[0], args.slice(1), {
    stdio: 'inherit',
    shell: process.platform === 'win32',
    env: process.env,
  });

  if (result.error) {
    console.error(result.error.message);
    process.exit(1);
  }

  process.exit(result.status ?? 0);
}

if (require.main === module) run();

module.exports = { exposeFrontendBuildEnvironment };
