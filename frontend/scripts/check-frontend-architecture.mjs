import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const failures = [];
const budgets = [
  ['app/layout.tsx', 120],
  ['app/globals.css', 560],
  ['components/layout/app-shell.tsx', 150],
  ['app/(app)/layout.tsx', 100],
];

for (const [file, limit] of budgets) {
  const absolute = path.join(root, file);
  if (!fs.existsSync(absolute)) {
    failures.push(`${file} is missing.`);
    continue;
  }
  const lines = fs.readFileSync(absolute, 'utf8').split(/\r?\n/).length;
  if (lines > limit) failures.push(`${file} has ${lines} lines; limit is ${limit}.`);
}

for (const owner of [
  'analytics.ts',
  'auth.ts',
  'content.ts',
  'integrations.ts',
  'opportunities.ts',
  'projects.ts',
  'prompts.ts',
  'providers.ts',
  'runs.ts',
  'traffic.ts',
  'visibility.ts',
]) {
  if (!fs.existsSync(path.join(root, 'lib', 'api', owner))) {
    failures.push(`lib/api/${owner} is missing.`);
  }
}

const facade = path.join(root, 'lib', 'api', 'index.ts');
if (fs.existsSync(facade)) {
  const source = fs.readFileSync(facade, 'utf8');
  if (/\bfetch\s*\(/.test(source) || /from\s+['"]\.\/client['"]/.test(source)) {
    failures.push('lib/api/index.ts must not own transport.');
  }
}

if (failures.length) {
  console.error(failures.join('\n'));
  process.exit(1);
}
console.log('Frontend architecture guard passed.');
