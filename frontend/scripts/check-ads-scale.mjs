/**
 * ADS scale guard (F1) — the fifth check:policy script.
 *
 * Keeps the type and spacing scales from drifting off the ADS ladders the
 * design system now runs on (docs/design.md §7–§8):
 *
 *   1. No `tracking-*` utilities. ADS defines NO letter-spacing tokens —
 *      tracking is 0 at every step — so a tracked class is always a
 *      hand-authored exception. Letter-spacing lives nowhere but the CSS
 *      the tokens own.
 *   2. No arbitrary type values (`text-[13px]`, `leading-[0.8]`). A size
 *      that does not exist on the ladder is a missing rung or a mistake,
 *      not a one-off. `text-[length:…]` is exempted: it is the escape
 *      hatch Tailwind itself provides for `var()` references such as the
 *      table's `text-[length:var(--table-font-size)]`.
 *   3. No `text-data-lg` — the retired 22px step. It had zero call sites
 *      when the ADS ladder replaced it; this keeps it dead.
 *   4. Off-ladder Tailwind spacing steps (the 10/14/28/36/44/56px rungs of
 *      the built-in 4px scale, which have no ADS `space.*` equivalent).
 *      The sweep consumed the last four sites (all in components/auth/**),
 *      so the ceiling is pinned at 0 and any new site fails immediately.
 *
 * Rules 1, 2 and 4 are hard gates at zero: the sweeps removed every
 * violation in the phases that introduced or ratcheted this guard, so any
 * new `tracking-*`, arbitrary type or off-ladder spacing class fails
 * immediately.
 *
 * Marketing note: the marketing sweep HAS landed, so all four rules now scan
 * every tree — `components/marketing/`, `app/(marketing)/` and
 * `lib/marketing-content/` included. The sweep removed 70 off-ladder spacing
 * sites (25 of them a single `gap-2.5`) and collapsed eight ad-hoc icon sizes
 * onto three rungs. The only carve-out is `CONTROL_HEIGHT_OWNER` below.
 *
 * Run: node scripts/check-ads-scale.mjs
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const ROOT = process.cwd();
const SEARCH_ROOTS = ['app', 'components', 'lib'];

/* Ceilings — see the header comment. All three rules swept to zero and are
   now hard gates; a new violation fails the build, it does not re-open a
   ratchet. */
const TRACKING_CEILING = 0;
const ARBITRARY_TYPE_CEILING = 0;
const OFF_LADDER_CEILING = 0;

/**
 * The one file allowed off the spacing ladder, and only because what it holds
 * is not spacing: the marketing control-height ladder (40/48/56px). See the
 * skip below and the docblock on `SIZE` in the file itself.
 */
const CONTROL_HEIGHT_OWNER = 'components/marketing/primitives/button.tsx';

const TRACKING_PATTERN = /\btracking-(?:tight|normal|wide|wider|\[)/g;
const ARBITRARY_TEXT_PATTERN = /\btext-\[(?!length:)/g;
const ARBITRARY_LEADING_PATTERN = /\bleading-\[/g;
const RETIRED_TYPE_PATTERN = /\btext-data-lg\b/;
const OFF_LADDER_PATTERN =
  /\b(?:[mp][trblxye]?|gap(?:-[xy])?|space-[xy]|size|[wh]|inset(?:-[xy])?|top|right|bottom|left|start|end)-(?:2\.5|3\.5|7|9|11|13|14|18)\b/g;

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

/** Every `file:line` on which `pattern` (global) matches at least once. */
function sites(file, lines, pattern) {
  const hits = [];
  lines.forEach((line, index) => {
    pattern.lastIndex = 0;
    if (pattern.test(line)) hits.push(`${file}:${index + 1}`);
  });
  return hits;
}

function countMatches(lines, pattern) {
  pattern.lastIndex = 0;
  return lines.reduce((total, line) => total + (line.match(pattern)?.length ?? 0), 0);
}

const violations = [];
const trackingSites = [];
const arbitraryTypeSites = [];
let offLadderCount = 0;

for (const root of SEARCH_ROOTS) {
  const rootPath = join(ROOT, root);
  if (!existsSync(rootPath)) continue;

  for (const absolute of walk(rootPath)) {
    const file = relative(ROOT, absolute).replaceAll('\\', '/');
    const lines = readFileSync(absolute, 'utf8').split(/\r?\n/);

    trackingSites.push(...sites(file, lines, TRACKING_PATTERN));
    for (const [index, line] of lines.entries()) {
      if (RETIRED_TYPE_PATTERN.test(line)) {
        violations.push(
          `${file}:${index + 1}: \`text-data-lg\` is retired — use the ADS type ladder.`,
        );
      }
    }
    // Rules 2 and 4 now cover marketing too — the marketing sweep landed, so
    // both ladders are shared by both surfaces.
    arbitraryTypeSites.push(...sites(file, lines, ARBITRARY_TEXT_PATTERN));
    arbitraryTypeSites.push(...sites(file, lines, ARBITRARY_LEADING_PATTERN));

    // The one carve-out, and it is rule 4 ONLY: the marketing control-height
    // ladder (40/48/56, primitives/button.tsx). A control height is chrome,
    // not spacing — the same exception the 72px nav bar already takes — and
    // all three live in one file, so a page cannot invent a fourth. Rule 2
    // still applies here: an arbitrary TYPE value in this file is a mistake
    // like anywhere else, and exempting the whole file would hide it.
    if (file === CONTROL_HEIGHT_OWNER) continue;
    offLadderCount += countMatches(lines, OFF_LADDER_PATTERN);
  }
}

if (trackingSites.length > TRACKING_CEILING) {
  violations.push(
    `tracking-* utilities: ${trackingSites.length} found, ceiling is ${TRACKING_CEILING}. ` +
      `ADS has no letter-spacing rungs — the count may only go down.\n    ${trackingSites.join('\n    ')}`,
  );
}
if (arbitraryTypeSites.length > ARBITRARY_TYPE_CEILING) {
  violations.push(
    `arbitrary type values: ${arbitraryTypeSites.length} found, ceiling is ${ARBITRARY_TYPE_CEILING}. ` +
      `Use a --text-* / --leading-* ladder step — the count may only go down.\n    ${arbitraryTypeSites.join('\n    ')}`,
  );
}
if (offLadderCount > OFF_LADDER_CEILING) {
  violations.push(
    `off-ladder spacing steps: ${offLadderCount} found, ceiling is ${OFF_LADDER_CEILING}. ` +
      'The ADS space ladder has no 10/14/28/36/44/56px rungs — re-pin the ceiling only by REMOVING sites.',
  );
}

if (violations.length) {
  console.error('ADS scale guard failed:');
  for (const v of violations) console.error(`- ${v}`);
  process.exit(1);
}

console.log(
  `ADS scale guard: OK (tracking ${trackingSites.length}/${TRACKING_CEILING}, ` +
    `arbitrary type ${arbitraryTypeSites.length}/${ARBITRARY_TYPE_CEILING}, ` +
    `off-ladder spacing ${offLadderCount}/${OFF_LADDER_CEILING})`,
);
