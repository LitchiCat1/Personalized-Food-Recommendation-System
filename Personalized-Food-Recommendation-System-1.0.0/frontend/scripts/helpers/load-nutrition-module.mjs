import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const lib = path.resolve(fileURLToPath(new URL('../../lib/', import.meta.url)));
const cache = new Map();

export function loadNutritionModule(name) {
  const filename = path.resolve(lib, `${name}.ts`);
  if (!filename.startsWith(`${lib}${path.sep}`)) throw new Error('Unexpected module path');
  if (cache.has(filename)) return cache.get(filename).exports;
  const module = { exports: {} };
  cache.set(filename, module);
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  new Function('require', 'module', 'exports', code)((id) => {
    if (!id.startsWith('./nutrition-')) throw new Error(`Unexpected runtime dependency: ${id}`);
    return loadNutritionModule(id.slice(2));
  }, module, module.exports);
  return module.exports;
}
