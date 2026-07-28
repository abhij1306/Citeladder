/**
 * Design-token guard (F1).
 *
 * Asserts that the token files declare every name documented in
 * docs/design.md. If a token is renamed/removed in design.md, update the lists
 * below to match — the CSS is the source of truth for VALUES, design.md for the
 * NAME SET.
 *
 * Five files, four namespaces:
 *   · app/ds-tokens.css              the Atlassian primitive layer (`--ds-*`),
 *                                    ported verbatim from @atlaskit/tokens
 *   · app/globals.css                the app COLOUR semantic layer, every
 *                                    value of which resolves to a `var(--ds-*)`
 *   · app/ds-type.css                the type layer (--text-* ladder, weights,
 *                                    leading) — split out of globals.css
 *   · app/ds-space.css               the space layer (--space-* ladder,
 *                                    density, geometry, radii) — same split
 *   · app/(marketing)/marketing-theme.css
 *                                    the independent marketing creative system
 *                                    (`--mkt-*`, docs/design.md §"Marketing
 *                                    creative system")
 *
 * The `--ds-*` list is checked first and hard-fails on its own: a missing
 * primitive makes every semantic token that references it resolve to nothing,
 * which is a more confusing failure than a missing semantic name.
 *
 * Run: node scripts/check-design-tokens.mjs
 */
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const root = process.cwd();
const cssPath = join(root, 'app', 'globals.css');
const dsCssPath = join(root, 'app', 'ds-tokens.css');
const dsTypeCssPath = join(root, 'app', 'ds-type.css');
const dsSpaceCssPath = join(root, 'app', 'ds-space.css');
const appChromeCssPath = join(root, 'app', 'app-chrome.css');
const mktCssPath = join(root, 'app', '(marketing)', 'marketing-theme.css');

for (const [label, path] of [
  ['app/globals.css', cssPath],
  ['app/ds-tokens.css (the ADS primitive layer)', dsCssPath],
  ['app/ds-type.css (the type layer)', dsTypeCssPath],
  ['app/ds-space.css (the space layer)', dsSpaceCssPath],
  ['app/app-chrome.css (the chrome rules)', appChromeCssPath],
  ['app/(marketing)/marketing-theme.css', mktCssPath],
]) {
  if (!existsSync(path)) {
    console.error(`check-design-tokens: ${label} is missing.`);
    process.exit(1);
  }
}
// The app-token loops match against the three app token owners together: the
// type and space layers were split out of globals.css, so a token that moved
// files must not read as missing.
const css = [
  readFileSync(cssPath, 'utf8'),
  readFileSync(dsTypeCssPath, 'utf8'),
  readFileSync(dsSpaceCssPath, 'utf8'),
  readFileSync(appChromeCssPath, 'utf8'),
].join('\n');
const dsCss = readFileSync(dsCssPath, 'utf8');
const mktCss = readFileSync(mktCssPath, 'utf8');

/**
 * Atlassian primitives that MUST be declared in app/ds-tokens.css. globals.css
 * resolves every semantic token through one of these, so a missing name here
 * makes a semantic token silently resolve to nothing — the failure mode this
 * list exists to catch. The nine accent hues are generated rather than listed:
 * the whole point of the ramp is that it is uniform.
 */
const ACCENT_HUES = [
  'blue',
  'green',
  'red',
  'orange',
  'yellow',
  'teal',
  'purple',
  'magenta',
  'gray',
];
const ACCENT_STEPS = ['subtlest', 'subtler', 'subtle', 'bolder', 'text'];

const requiredDsVars = [
  // Elevation surfaces — the tint ladder that replaced shadow
  'ds-surface',
  'ds-surface-hovered',
  'ds-surface-pressed',
  'ds-surface-sunken',
  'ds-surface-raised',
  'ds-surface-overlay',
  'ds-surface-canvas',
  // Neutral + input backgrounds
  'ds-background-neutral',
  'ds-background-neutral-hovered',
  'ds-background-neutral-pressed',
  'ds-background-neutral-bold',
  'ds-background-disabled',
  'ds-background-input',
  'ds-background-selected',
  // Text
  'ds-text',
  'ds-text-subtle',
  'ds-text-subtlest',
  'ds-text-disabled',
  'ds-text-inverse',
  // Borders
  'ds-border',
  'ds-border-subtle',
  'ds-border-bold',
  'ds-border-input',
  'ds-border-focused',
  'ds-border-selected',
  // Brand + link
  'ds-background-brand-bold',
  'ds-background-brand-bold-hovered',
  'ds-background-brand-bold-pressed',
  'ds-background-brand-subtlest',
  'ds-background-brand-subtler',
  'ds-link',
  // Danger solids (destructive button fill)
  'ds-background-danger-bold',
  'ds-background-danger-bold-hovered',
  // Elevation + shape + scrim
  'ds-shadow-overlay',
  'ds-radius-xsmall',
  'ds-radius-small',
  'ds-radius-medium',
  'ds-radius-large',
  'ds-radius-xlarge',
  'ds-border-width-focused',
  'ds-blanket',
  // Type primitives (consumed by ds-type.css)
  'ds-font-size-050',
  'ds-font-size-075',
  'ds-font-size-100',
  'ds-font-size-200',
  'ds-font-size-300',
  'ds-font-size-400',
  'ds-font-size-500',
  'ds-font-size-600',
  'ds-font-lineHeight-100',
  'ds-font-lineHeight-200',
  'ds-font-lineHeight-300',
  'ds-font-lineHeight-400',
  'ds-font-lineHeight-500',
  'ds-font-lineHeight-600',
  'ds-font-weight-regular',
  'ds-font-weight-medium',
  'ds-font-weight-semibold',
  'ds-font-weight-bold',
  // Space primitives (consumed by ds-space.css)
  'ds-space-0',
  'ds-space-025',
  'ds-space-050',
  'ds-space-075',
  'ds-space-100',
  'ds-space-150',
  'ds-space-200',
  'ds-space-250',
  'ds-space-300',
  'ds-space-400',
  'ds-space-500',
  'ds-space-600',
  'ds-space-800',
  'ds-space-1000',
  ...ACCENT_HUES.flatMap((hue) => ACCENT_STEPS.map((step) => `ds-accent-${hue}-${step}`)),
];

// Raw CSS variables that MUST be declared (`--name:`) across the three app
// token owners (globals.css for colour, ds-type.css for type, ds-space.css
// for space — matched against the concatenation of the three).
//
// The Figma primitive ramps (--blue-50..900, --neutral-0..900) are GONE: the
// primitive layer is now app/ds-tokens.css and its --ds-* names are checked
// separately below. globals.css owns semantics only.
const requiredVars = [
  // Fonts
  'font-primary-family',
  'font-mono-family',
  'font-display-family',
  // Surfaces
  'bg-base',
  'bg-alt',
  'bg-panel',
  'bg-elevated',
  'bg-well',
  'bg-active',
  'bg-input',
  'bg-sidebar',
  'bg-inverse',
  'surface-overlay',
  // Borders
  'border-subtle',
  'border',
  'border-strong',
  'border-focus',
  // Text
  'text-primary',
  'text-secondary',
  'text-muted',
  'text-subtle',
  'text-inverse',
  'text-on-inverse',
  'text-link',
  // Accent
  'accent',
  'accent-hover',
  'accent-active',
  'accent-fg',
  'accent-subtle',
  'accent-soft',
  'accent-border',
  'accent-text',
  // Status
  'success',
  'success-bg',
  'success-border',
  'success-text',
  'warning',
  'warning-bg',
  'warning-border',
  'warning-text',
  'danger',
  'danger-solid',
  'danger-solid-hover',
  'danger-fg',
  'danger-bg',
  'danger-border',
  'danger-text',
  'info',
  'info-bg',
  'info-border',
  'info-text',
  'neutral-bg',
  // Sentiment
  'sentiment-positive',
  'sentiment-positive-bg',
  'sentiment-positive-text',
  'sentiment-neutral',
  'sentiment-neutral-bg',
  'sentiment-neutral-text',
  'sentiment-negative',
  'sentiment-negative-bg',
  'sentiment-negative-text',
  'value-placeholder',
  // Citation classification (+ borders)
  'citation-owned',
  'citation-owned-bg',
  'citation-owned-border',
  'citation-owned-text',
  'citation-competitor',
  'citation-competitor-bg',
  'citation-competitor-border',
  'citation-competitor-text',
  'citation-third-party',
  'citation-third-party-bg',
  'citation-third-party-border',
  'citation-third-party-text',
  // Run status
  'run-draft',
  'run-draft-bg',
  'run-queued',
  'run-queued-bg',
  'run-running',
  'run-running-bg',
  'run-analyzing',
  'run-analyzing-bg',
  'run-completed',
  'run-completed-bg',
  'run-partial',
  'run-partial-bg',
  'run-failed',
  'run-failed-bg',
  'run-cancelled',
  'run-cancelled-bg',
  // Score bands (+ text/ring/border)
  'score-low',
  'score-low-bg',
  'score-low-border',
  'score-low-text',
  'score-low-ring',
  'score-mid',
  'score-mid-bg',
  'score-mid-border',
  'score-mid-text',
  'score-mid-ring',
  'score-good',
  'score-good-bg',
  'score-good-border',
  'score-good-text',
  'score-good-ring',
  'score-high',
  'score-high-bg',
  'score-high-border',
  'score-high-text',
  'score-high-ring',
  // Chart palette (--chart-1..8, from the ADS accent ramp) + series aliases
  'chart-1',
  'chart-2',
  'chart-3',
  'chart-4',
  'chart-5',
  'chart-6',
  'chart-7',
  'chart-8',
  'series-1',
  'series-2',
  'series-3',
  'series-4',
  'series-5',
  'series-other',
  'chart-tooltip-bg',
  'chart-tooltip-fg',
  // Shadows / elevation — rungs + semantic aliases (cards rest on the raised
  // rung; only overlays and the interactive-card hover lift use the overlay rung)
  'shadow-1',
  'shadow-2',
  'shadow-3',
  'shadow-4',
  'shadow-xs-value',
  'shadow-sm-value',
  'shadow-card-value',
  'shadow-card-hover-value',
  'shadow-elevated-value',
  'shadow-lg-value',
  'shadow-modal',
  'focus-ring',
  'overlay-scrim',
  // Skeleton
  'skeleton-base',
  'skeleton-highlight',
  // Weights
  'weight-normal',
  'weight-medium',
  'weight-semibold',
  'weight-bold',
  // Line heights
  'leading-none',
  'leading-tight',
  'leading-snug',
  'leading-normal',
  // Spacing — the ADS space.* ladder (no 28px/56px rungs; 2px/6px exist)
  'space-0',
  'space-025',
  'space-050',
  'space-075',
  'space-100',
  'space-150',
  'space-200',
  'space-250',
  'space-300',
  'space-400',
  'space-500',
  'space-600',
  'space-800',
  'space-1000',
  // Density + shell geometry
  'card-padding',
  'card-gap',
  'content-gutter',
  'sidebar-width',
  'topbar-height',
  'nav-item-height',
  'content-max-width',
  // Radii
  'radius-xs',
  'radius-sm',
  'radius-md',
  'radius-lg',
  'radius-xl',
  'radius-2xl',
  'radius-full',
  // Controls
  'control-height-sm',
  'control-height',
  'control-height-lg',
  'interactive-border-width',
  // Table
  'table-row-height',
  'table-header-height',
  'table-cell-padding-x',
  'table-cell-padding-y',
  'table-font-size',
  'table-header-font-size',
  // Segmented
  'segmented-bg',
  // Motion
  'transition-fast',
  'transition-base',
  'transition-slow',
];

// Type-scale sizes live in the @theme inline bridge (Tailwind --text-* namespace).
// The ADS ladder (docs/design.md §7): 13px/15px rungs do not exist, the two
// heading composites carry their own names, and text-data-lg is retired.
const requiredTypeScale = [
  'text-2xs',
  'text-xs',
  'text-sm',
  'text-base',
  'text-heading-xs',
  'text-heading-sm',
  'text-lg',
  'text-xl',
  'text-2xl',
  'text-hero',
  'text-display-1',
  'text-display-2',
];

// Bridged @theme colors that MUST exist so components can reference them.
const requiredBridged = [
  'color-background',
  'color-panel',
  'color-active',
  'color-input',
  'color-surface-inverse',
  'color-chart-tooltip-fg',
  'color-foreground',
  'color-secondary',
  'color-muted',
  'color-on-inverse',
  'color-border',
  'color-accent',
  'color-success',
  'color-warning',
  'color-danger',
  'color-danger-solid',
  'color-danger-solid-hover',
  'color-info',
  'color-sentiment-positive',
  'color-sentiment-neutral',
  'color-sentiment-negative',
  'color-citation-owned',
  'color-citation-competitor',
  'color-citation-third-party',
  'color-run-draft',
  'color-run-queued',
  'color-run-running',
  'color-run-analyzing',
  'color-run-completed',
  'color-run-partial',
  'color-run-failed',
  'color-run-cancelled',
  'color-score-low',
  'color-score-mid',
  'color-score-good',
  'color-score-high',
];

// Marketing/auth "Proof" tokens that MUST be declared in
// app/(marketing)/marketing-theme.css — the contract documented in
// docs/design.md ("Marketing creative system"). These are Tailwind `@theme`
// keys, so each one also has to keep generating its utility: renaming any of
// them silently drops classes across the whole marketing surface, which is
// exactly the failure this guard exists to catch.
const requiredMktVars = [
  // Type — one face (Geist alias), eight steps
  'font-mkt-display',
  'text-mkt-d1',
  'text-mkt-d2',
  'text-mkt-d3',
  'text-mkt-d4',
  'text-mkt-lead',
  'text-mkt-body',
  'text-mkt-sm',
  'text-mkt-meta',
  // Canvas + ink
  'color-mkt-paper',
  'color-mkt-surface',
  'color-mkt-wash',
  'color-mkt-ink',
  'color-mkt-ink-soft',
  'color-mkt-ink-muted',
  'color-mkt-line',
  // State hues, each with its AA-safe text form — except proof: the single
  // blue clears AA as both mark and text, so a -text sibling would be a
  // duplicate token, not a safety net (globals.test.ts "Proof contract").
  'color-mkt-proof',
  'color-mkt-evidence',
  'color-mkt-evidence-text',
  'color-mkt-signal',
  'color-mkt-signal-text',
  'color-mkt-amber',
  'color-mkt-amber-text',
  // Scene surface (the wallpaper display art)
  'color-mkt-sky',
  // Shape, layout, motion
  'radius-mkt-sm',
  'radius-mkt-lg',
  'container-mkt',
  'spacing-mkt-gutter',
  'spacing-mkt-nav',
  'ease-mkt-out',
];

const missing = [];

const missingDs = [];
for (const name of requiredDsVars) {
  const re = new RegExp(`--${name}\\s*:`);
  if (!re.test(dsCss)) missingDs.push(`--${name}`);
}

if (missingDs.length) {
  console.error(
    `Design-token guard failed: ${missingDs.length} Atlassian primitive(s) are missing from app/ds-tokens.css:`,
  );
  for (const m of missingDs) console.error(`- ${m}`);
  process.exit(1);
}

for (const name of requiredVars) {
  const re = new RegExp(`--${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*:`);
  if (!re.test(css)) missing.push(`--${name}`);
}
for (const name of requiredTypeScale) {
  const re = new RegExp(`--${name}\\s*:`);
  if (!re.test(css)) missing.push(`--${name} (type scale)`);
}
for (const name of requiredBridged) {
  const re = new RegExp(`--${name}\\s*:`);
  if (!re.test(css)) missing.push(`--${name} (@theme bridge)`);
}

if (missing.length) {
  console.error(
    `Design-token guard failed: ${missing.length} token(s) documented in docs/design.md are missing from app/globals.css + app/ds-type.css + app/ds-space.css + app/app-chrome.css:`,
  );
  for (const m of missing) console.error(`- ${m}`);
  process.exit(1);
}

const missingMkt = [];
for (const name of requiredMktVars) {
  const re = new RegExp(`--${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*:`);
  if (!re.test(mktCss)) missingMkt.push(`--${name}`);
}

if (missingMkt.length) {
  console.error(
    `Design-token guard failed: ${missingMkt.length} marketing token(s) are missing from app/(marketing)/marketing-theme.css:`,
  );
  for (const m of missingMkt) console.error(`- ${m}`);
  process.exit(1);
}

console.log(
  `design-token guard: OK (${requiredDsVars.length} ADS primitives in ds-tokens.css, ${
    requiredVars.length + requiredTypeScale.length + requiredBridged.length
  } app tokens across globals/ds-type/ds-space/app-chrome.css, ${requiredMktVars.length} marketing tokens in marketing-theme.css)`,
);
