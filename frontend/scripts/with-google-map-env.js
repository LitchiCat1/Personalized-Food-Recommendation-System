const { spawnSync } = require('node:child_process');

function exposeFrontendBuildEnvironment(env, { sameOriginApi = false } = {}) {
  // build:local：網站由後端一起提供，API 就在同一個網址。蓋過 .env.local 的
  // 127.0.0.1——那個位址在別人的手機上指的是手機自己。
  if (sameOriginApi) env.EXPO_PUBLIC_API_BASE_URL = 'same-origin';

  const mappings = [
    ['EXPO_PUBLIC_GOOGLE_MAPS_API_KEY', ['GOOGLE_PLACES_API_KEY', 'GOOGLE_MAPS_API_KEY']],
    // 前後端用同一個開關：後端設 AUTH_REQUIRED=false 時，前端也跳過登入畫面
    ['EXPO_PUBLIC_AUTH_REQUIRED', ['AUTH_REQUIRED']],
  ];

  for (const [publicKey, sourceKeys] of mappings) {
    if (env[publicKey]) continue;
    const sourceValue = sourceKeys.map((key) => env[key]).find(Boolean);
    if (sourceValue) env[publicKey] = sourceValue;
  }

  return env;
}

function run() {
  const [, , ...rawArgs] = process.argv;
  const sameOriginApi = rawArgs[0] === '--same-origin';
  const args = sameOriginApi ? rawArgs.slice(1) : rawArgs;

  if (args.length === 0) {
    console.error('Usage: node scripts/with-google-map-env.js <command> [args...]');
    process.exit(1);
  }

  exposeFrontendBuildEnvironment(process.env, { sameOriginApi });

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
