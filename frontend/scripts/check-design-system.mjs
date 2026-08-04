import { readFileSync, readdirSync, statSync } from 'node:fs';
import { extname, join, relative, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const tokenOwner = join(root, 'app', 'globals.css');
const sourceExtensions = new Set(['.css', '.ts', '.tsx', '.js', '.mjs']);
const ignored = new Set(['node_modules', '.next', '.next-stale-codex', 'coverage', 'test-results']);
const violations = [];

function files(directory) {
  return readdirSync(directory).flatMap((name) => {
    if (ignored.has(name)) return [];
    const path = join(directory, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

for (const path of files(root)) {
  if (!sourceExtensions.has(extname(path))) continue;
  const source = readFileSync(path, 'utf8');
  const label = relative(root, path).replaceAll('\\', '/');
  const legacyIdentifiers = [
    ['Search', 'ify'].join(''),
    ['search', 'ify'].join(''),
    ['--', 'ds-'].join(''),
    ['--', 'mkt-'].join(''),
    ['data', '-theme'].join(''),
    ['Theme', 'Toggle'].join(''),
  ];
  for (const legacy of legacyIdentifiers) {
    if (source.includes(legacy)) violations.push(`${label}: legacy identifier ${legacy}`);
  }
  if (
    path !== tokenOwner &&
    path !== import.meta.filename &&
    /(?<![\w-])#[0-9a-f]{3,8}(?![\w-])/i.test(source)
  ) {
    violations.push(`${label}: raw color outside app/globals.css`);
  }
  if (path !== tokenOwner && path !== import.meta.filename && /@theme\b/.test(source)) {
    violations.push(`${label}: @theme outside app/globals.css`);
  }
}

if (violations.length) {
  console.error(violations.join('\n'));
  process.exit(1);
}
console.log('CiteLadder design-system policy passed.');
