import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const frontend = path.join(root, 'frontend');
const outputIndex = process.argv.indexOf('--output');
if (outputIndex < 0 || !process.argv[outputIndex + 1]) {
  throw new Error('Usage: node tools/verify_nutrition_frontend.mjs --output <manifest.json>');
}
const output = path.resolve(root, process.argv[outputIndex + 1]);
const logDir = fs.mkdtempSync(path.join(os.tmpdir(), 'nutrition-frontend-check-'));
const tests = fs.readdirSync(path.join(frontend, 'scripts')).filter((name) => /^test-.*\.mjs$/.test(name)).sort();
const commands = [
  { name: 'frontend_tests', command: process.execPath, args: ['--test', '--test-reporter=tap', ...tests.map((file) => `scripts/${file}`)] },
  ...['typecheck', 'lint', 'build:web'].map((name) => ({ name, command: process.platform === 'win32' ? 'npm.cmd' : 'npm', args: ['run', name] })),
];
const checks = [];
for (const command of commands) {
  const started = Date.now();
  const result = spawnSync(command.command, command.args, {
    cwd: frontend, encoding: 'utf8', timeout: 240_000, maxBuffer: 16 * 1024 * 1024,
    shell: process.platform === 'win32' && command.command === 'npm.cmd',
    env: { ...process.env, NUTRILENS_SKIP_LOCAL_ENV: '1' },
  });
  const log = `${result.stdout ?? ''}\n${result.stderr ?? ''}`;
  fs.writeFileSync(path.join(logDir, `${command.name.replace(/:/g, '-')}.log`), log);
  const count = (label) => Number(log.match(new RegExp(`^# ${label} (\\d+)$`, 'm'))?.[1] ?? 0);
  const check = {
    name: command.name,
    command: command.name === 'frontend_tests' ? 'node --test --test-reporter=tap scripts/test-*.mjs' : `npm run ${command.name}`,
    exit_code: result.status,
    duration_ms: Date.now() - started,
    passed: result.status === 0,
    ...(command.name === 'frontend_tests' ? {
      tests: count('tests'), pass: count('pass'), fail: count('fail'), skipped: count('skipped'), files: tests,
    } : {}),
  };
  checks.push(check);
  process.stdout.write(`${check.name}: ${check.passed ? 'passed' : 'FAILED'}\n`);
  if (!check.passed) break;
}
const manifest = {
  schema_version: 1,
  generated_at: new Date().toISOString(),
  branch: spawnSync('git', ['branch', '--show-current'], { cwd: root, encoding: 'utf8' }).stdout?.trim() || null,
  scope: 'Phase3k scanner enrichment transport, versioned read models, coverage-aware aggregation and strict history validation; nullable dashboard/history UI not activated',
  paid_calls: 0,
  real_user_database_access: false,
  backend_snapshot_test: 'Pure Python services with socket disabled; mocked fetch; no live HTTP integration',
  checks,
  passed: checks.length === commands.length && checks.every((check) => check.passed),
  limitations: [
    'Does not test live Mongo, live AI/Tavily, photo accuracy, or native device input',
    'V2 OCR/dashboard/history/trend/recommendation UI and v2 retry dispatcher remain unconnected; scanner enrichment is capability-gated and off by default',
    'Web Locks coordinate updated cooperating tabs only; native remains one-runtime and old lockless tabs are not covered',
    'Missing or different queue backend target blocks replay; legacy binding and mixed-key reconciliation remain pending',
    'Rendered checks are recorded separately and are not rerun by this command',
    'Read-model completeness describes included recorded items in the declared query scope, not all food actually consumed',
    'Local summary means are unrounded; server history means retain Python one-decimal rounding and compatibility float averages',
    'History response has no explicit range anchor; internal consistency does not prove freshness or expected current dates',
  ],
};
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, `${JSON.stringify(manifest, null, 2)}\n`);
process.stdout.write(`Manifest: ${path.relative(root, output)}\nPrivate logs: ${logDir}\n`);
if (!manifest.passed) process.exitCode = 1;
