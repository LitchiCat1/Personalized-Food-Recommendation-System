const { spawnSync } = require('node:child_process');

const [, , ...args] = process.argv;

if (args.length === 0) {
  console.error('Usage: node scripts/with-google-map-env.js <command> [args...]');
  process.exit(1);
}

const googleKey = process.env.GOOGLE_PLACES_API_KEY || process.env.GOOGLE_MAPS_API_KEY;
if (googleKey && !process.env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY) {
  process.env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY = googleKey;
}

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
