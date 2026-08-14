import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const failures = [];
const budgets = [
  ['app/layout.tsx', 120],
  // Raised from 560 for the shared a11y primitives (skip link, anchor
  // scroll-margin, safe-area helpers, touch-action), then from 620 for the
  // `brand-canvas-*` roles and `border-bold` — the split auth/onboarding
  // surface is the one part of the app that is dark in every theme, and the
  // alternative was the raw palette classes it replaced. Token/recipe sprawl is
  // still what this budget guards.
  ['app/globals.css', 640],
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
  'ai-referrals.ts',
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
