/**
 * Token-escape + no-raw-hex guard (F1).
 *
 * Enforces the design.md token policy:
 *   1. Components must not use raw CSS-var Tailwind escapes like
 *      `bg-[var(--foo)]` — they must use the bridged semantic utilities.
 *   2. Raw hex colors live ONLY in app/globals.css theme blocks. No hex may
 *      appear in any component/app .tsx/.ts source.
 *   3. No raw Tailwind PALETTE colours (`text-indigo-600`, `border-slate-200`,
 *      `bg-emerald-100`, …). A hex was already banned by rule 2, but the
 *      palette classes were the same escape wearing a different hat, and they
 *      were the bigger leak in practice: the auth and onboarding screens ran
 *      entirely on indigo/slate, so they simply did not move when the design
 *      system was retuned — the app kept a violet accent while every token
 *      surface went blue. Semantic utilities only (`text-accent-text`,
 *      `border-border-subtle`, `bg-success-bg`, or the `mkt-` set on the
 *      marketing/auth surface).
 *   4. globals.css itself parses and contains the expected theme structure.
 *
 * Run: node scripts/check-token-escapes.mjs
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const ROOT = process.cwd();
const SEARCH_ROOTS = ['app', 'components', 'lib'];
const TOKEN_ESCAPE_PATTERN = /\b(?:bg|text|border|shadow|ring|fill|stroke)-(?:\[var\(--|\(--)/;
const RAW_HEX_PATTERN = /#[0-9a-fA-F]{3,8}\b/;

/** Tailwind's built-in palette ramps — banned in favour of semantic tokens. */
const PALETTE_HUES =
  'slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose';
/**
 * Every utility family that takes a COLOUR. Two of these are easy to miss and
 * are spelled out rather than folded into `border`/`ring`:
 *   · `border-t|r|b|l|s|e|x|y-` — a directional border still paints a colour,
 *     so `border-t-blue-500` is the same escape as `border-blue-500`.
 *   · `ring-offset-` — its own colour property, not a length.
 * `ring-offset` must precede `ring` only for readability; the engine
 * backtracks either way.
 */
const PALETTE_PREFIXES =
  'bg|text|border(?:-[trblsexy])?|ring-offset|ring|from|via|to|fill|stroke|decoration|outline|divide|accent|caret|shadow';
const RAW_PALETTE_PATTERN = new RegExp(
  String.raw`\b(?:${PALETTE_PREFIXES})-(?:${PALETTE_HUES})-(?:50|\d{3})\b`,
  'g',
);

function walk(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    const stats = statSync(path);
    if (stats.isDirectory()) return walk(path);
    if (!/\.(tsx|ts)$/.test(path)) return [];
    if (/\.(test|spec)\.(tsx|ts)$/.test(path)) return [];
    return [path];
  });
}

const violations = [];

for (const root of SEARCH_ROOTS) {
  const rootPath = join(ROOT, root);
  if (!existsSync(rootPath)) continue;
  for (const file of walk(rootPath)) {
    const normalized = relative(ROOT, file).replaceAll('\\', '/');
    const text = readFileSync(file, 'utf8');
    if (TOKEN_ESCAPE_PATTERN.test(text)) {
      violations.push(`${normalized}: raw CSS-var Tailwind escape (use a bridged token)`);
    }
    RAW_PALETTE_PATTERN.lastIndex = 0;
    const palette = [...new Set(text.match(RAW_PALETTE_PATTERN) ?? [])];
    if (palette.length) {
      violations.push(
        `${normalized}: raw Tailwind palette colour (use a semantic token): ${palette.join(', ')}`,
      );
    }
    if (RAW_HEX_PATTERN.test(text)) {
      violations.push(`${normalized}: raw hex color (no hex in component/app .ts/.tsx source)`);
    }
  }
}

// globals.css must exist and define both theme blocks.
const globalsPath = join(ROOT, 'app', 'globals.css');
if (!existsSync(globalsPath)) {
  violations.push('app/globals.css is missing — it is the single token source.');
} else {
  const css = readFileSync(globalsPath, 'utf8');
  if (!/:root\s*\{/.test(css)) violations.push('app/globals.css: missing :root light theme block.');
  if (!/html\[data-theme='dark'\]\s*\{/.test(css)) {
    violations.push("app/globals.css: missing html[data-theme='dark'] dark theme block.");
  }
  if (!/@theme inline\s*\{/.test(css)) {
    violations.push('app/globals.css: missing @theme inline Tailwind bridge.');
  }
}

if (violations.length) {
  console.error('Token-escape / no-raw-hex guard failed:');
  for (const v of violations) console.error(`- ${v}`);
  process.exit(1);
}

console.log('token-escape / no-raw-hex guard: OK');
