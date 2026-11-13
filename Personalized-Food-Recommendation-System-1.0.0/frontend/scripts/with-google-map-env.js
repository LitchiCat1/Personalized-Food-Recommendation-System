const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

// 跟後端 env_service.py 一樣的寫法：KEY=VALUE、# 開頭是註解、去掉前後引號
function readEnvFile(filePath) {
  let text;
  try {
    text = fs.readFileSync(filePath, 'utf8');
  } catch {
    return {};
  }

  const values = {};
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#') || !line.includes('=')) continue;
    const separator = line.indexOf('=');
    const key = line.slice(0, separator).trim();
    const value = line.slice(separator + 1).trim().replace(/^["']+|["']+$/g, '');
    if (key) values[key] = value;
  }
  return values;
}

// frontendEnv：frontend/.env*，Expo 打包時自己會讀，裡面寫了就照它的。
// backendEnv：本機的金鑰只放在 backend/.env.local（後端也讀這份），不用再抄一份到前端。
function exposeFrontendBuildEnvironment(
  env,
  { sameOriginApi = false, frontendEnv = {}, backendEnv = {} } = {},
) {
  // build:local：網站由後端一起提供，API 就在同一個網址。蓋過 .env.local 的
  // 127.0.0.1——那個位址在別人的手機上指的是手機自己。
  if (sameOriginApi) env.EXPO_PUBLIC_API_BASE_URL = 'same-origin';

  const mappings = [
    // EXPO_PUBLIC_* 會原樣寫進網站的 JS，任何開網站的人都讀得到。先前這裡拿後端呼叫
    // Places（按次計費）的 GOOGLE_PLACES_API_KEY 頂替，伺服器金鑰就跟著公開了。
    // 地圖只用另外建、限制網域與 API 的瀏覽器金鑰。
    ['EXPO_PUBLIC_GOOGLE_MAPS_API_KEY', ['GOOGLE_MAPS_BROWSER_KEY']],
    // 前後端用同一個開關：後端設 AUTH_REQUIRED=false 時，前端也跳過登入畫面
    ['EXPO_PUBLIC_AUTH_REQUIRED', ['AUTH_REQUIRED']],
  ];

  for (const [publicKey, sourceKeys] of mappings) {
    if (env[publicKey] || frontendEnv[publicKey]) continue;
    const sourceValue = [env, backendEnv]
      .flatMap((source) => sourceKeys.map((key) => source[key]))
      .find(Boolean);
    if (sourceValue) env[publicKey] = sourceValue;
  }

  return env;
}

function readLocalEnvFiles() {
  const frontendDir = path.resolve(__dirname, '..');
  const repoRoot = path.resolve(frontendDir, '..');
  return {
    frontendEnv: {
      ...readEnvFile(path.join(frontendDir, '.env')),
      ...readEnvFile(path.join(frontendDir, '.env.local')),
    },
    // 後端是根目錄的 .env.local 優先
    backendEnv: {
      ...readEnvFile(path.join(repoRoot, 'backend', '.env.local')),
      ...readEnvFile(path.join(repoRoot, '.env.local')),
    },
  };
}

function run() {
  const [, , ...rawArgs] = process.argv;
  const sameOriginApi = rawArgs[0] === '--same-origin';
  const args = sameOriginApi ? rawArgs.slice(1) : rawArgs;

  if (args.length === 0) {
    console.error('Usage: node scripts/with-google-map-env.js <command> [args...]');
    process.exit(1);
  }

  exposeFrontendBuildEnvironment(process.env, { sameOriginApi, ...readLocalEnvFiles() });

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
