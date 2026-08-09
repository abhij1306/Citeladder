import { readFileSync, readdirSync, statSync } from 'node:fs';
import { extname, join, relative, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const tokenOwner = join(root, 'app', 'globals.css');
const sourceExtensions = new Set(['.css', '.ts', '.tsx', '.js', '.mjs']);
const ignored = new Set(['node_modules', '.next', '.next-stale-codex', 'coverage', 'test-results']);
const violations = [];

const requiredWebsiteContracts = new Map([
  [
    join(root, 'app', 'website-type.css'),
    [
      '.website-hero-display',
      'font-size: 2.75rem;',
      'letter-spacing: -0.04em;',
      '.website-page-title',
      'font-size: 2.5rem;',
      'letter-spacing: -0.035em;',
      '.website-section-heading',
      '.website-feature-heading',
      '.website-small-heading',
      '.website-lead',
      '.website-body',
      '.website-nav',
      '.website-label',
      '.website-eyebrow',
      '.website-data-display',
      'color: var(--color-foreground);',
      'color: var(--color-secondary);',
      'color: var(--color-muted);',
    ],
  ],
  [join(root, 'components', 'marketing', 'landing', 'hero.tsx'), ['website-hero-display']],
  [join(root, 'components', 'marketing', 'primitives', 'page-hero.tsx'), ['website-page-title']],
  [
    join(root, 'components', 'marketing', 'primitives', 'section.tsx'),
    ['website-section-heading', 'website-feature-heading'],
  ],
  [join(root, 'components', 'auth', 'auth-form.tsx'), ['website-small-heading', 'website-body']],
]);

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
    ['Public', ' Sans'].join(''),
    ['Public', '_Sans'].join(''),
    ['font', '-public-sans'].join(''),
    ['marketing', '-atmosphere'].join(''),
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
  if (!label.startsWith('components/ui/') && /from\s+['"]@radix-ui\//.test(source)) {
    violations.push(`${label}: feature code must use components/ui instead of importing Radix`);
  }
  const ownsWebsiteEditorialCopy =
    (label.startsWith('components/marketing/') &&
      label !== 'components/marketing/landing/agent-console.tsx' &&
      !label.startsWith('components/marketing/scenes/')) ||
    label.startsWith('components/auth/') ||
    label.startsWith('components/onboarding/');
  if (
    ownsWebsiteEditorialCopy &&
    /<(?:h[1-6]|p)\b[^>]*className=['"][^'"]*\btext-(?:2xs|xs|sm|base|lg|xl|2xl|3xl|4xl|5xl)\b/.test(
      source,
    )
  ) {
    violations.push(`${label}: editorial headings and paragraphs must use named website roles`);
  }
}

for (const [path, requiredSnippets] of requiredWebsiteContracts) {
  const source = readFileSync(path, 'utf8');
  const label = relative(root, path).replaceAll('\\', '/');
  for (const snippet of requiredSnippets) {
    if (!source.includes(snippet)) violations.push(`${label}: missing website contract ${snippet}`);
  }
}

if (violations.length) {
  console.error(violations.join('\n'));
  process.exit(1);
}
console.log('CiteLadder design-system policy passed.');
