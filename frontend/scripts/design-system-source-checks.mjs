import { readFileSync } from 'node:fs';
import { join, relative } from 'node:path';

import ts from 'typescript';

const EDITORIAL_TAGS = new Set(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p']);
const EDITORIAL_SIZE = /\btext-(?:2xs|xs|sm|base|lg|xl|2xl|3xl|4xl|5xl)\b/;
const WEBSITE_CSS = 'app/website-type.css';
const TOKEN_CSS = 'app/globals.css';
const MINIMUM_NORMAL_TEXT_CONTRAST = 4.5;
const LIGHT_SURFACE_TOKENS = [
  '--color-background',
  '--color-background-alt',
  '--color-panel',
  '--color-panel-tonal',
  '--color-well',
  '--color-active',
];
const NEUTRAL_TEXT_TOKENS = [
  '--color-foreground',
  '--color-secondary',
  '--color-muted',
  '--color-subtle',
];

const CSS_BLOCK_CONTRACTS = new Map([
  ['.website-hero-display', ['font-size: 2.75rem', 'letter-spacing: -0.04em']],
  ['.website-page-title', ['font-size: 2.5rem', 'letter-spacing: -0.035em']],
  ['.website-section-heading', []],
  ['.website-feature-heading', []],
  ['.website-small-heading', []],
  ['.auth-form-title', ['font-size: 1.375rem', 'letter-spacing: -0.01em']],
  ['.website-lead', []],
  ['.website-body', []],
  ['.website-nav', []],
  ['.website-label', []],
  ['.website-eyebrow', []],
  ['.website-data-display', []],
]);

const ROLE_COLOR_CONTRACTS = new Map([
  ['.website-hero-display', 'color: var(--color-foreground)'],
  ['.website-page-title', 'color: var(--color-foreground)'],
  ['.website-section-heading', 'color: var(--color-foreground)'],
  ['.website-feature-heading', 'color: var(--color-foreground)'],
  ['.website-small-heading', 'color: var(--color-foreground)'],
  ['.website-nav', 'color: var(--color-foreground)'],
  ['.website-data-display', 'color: var(--color-foreground)'],
  ['.website-lead', 'color: var(--color-secondary)'],
  ['.website-body', 'color: var(--color-secondary)'],
  ['.website-label', 'color: var(--color-muted)'],
  ['.website-eyebrow', 'color: var(--color-muted)'],
]);

const JSX_ROLE_CONTRACTS = new Map([
  ['components/marketing/landing/hero.tsx', ['website-hero-display']],
  ['components/marketing/primitives/page-hero.tsx', ['website-page-title']],
  [
    'components/marketing/primitives/section.tsx',
    ['website-section-heading', 'website-feature-heading'],
  ],
  ['components/auth/auth-form.tsx', ['auth-form-title', 'website-body']],
]);

function staticBindings(sourceFile) {
  const bindings = new Map();
  const visit = (node) => {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      bindings.set(node.name.text, node.initializer);
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return bindings;
}

function classFragments(node, bindings, seen = new Set()) {
  if (!node) return [];
  if (ts.isStringLiteralLike(node)) return [node.text];
  if (ts.isTemplateExpression(node)) {
    return [
      node.head.text,
      ...node.templateSpans.flatMap((span) => [
        ...classFragments(span.expression, bindings, seen),
        span.literal.text,
      ]),
    ];
  }
  if (
    ts.isParenthesizedExpression(node) ||
    ts.isAsExpression(node) ||
    ts.isSatisfiesExpression(node)
  ) {
    return classFragments(node.expression, bindings, seen);
  }
  if (ts.isIdentifier(node)) {
    if (seen.has(node.text)) return [];
    const initializer = bindings.get(node.text);
    if (!initializer) return [];
    return classFragments(initializer, bindings, new Set([...seen, node.text]));
  }
  if (ts.isElementAccessExpression(node)) {
    let target = ts.isIdentifier(node.expression)
      ? bindings.get(node.expression.text)
      : node.expression;
    while (
      target &&
      (ts.isParenthesizedExpression(target) ||
        ts.isAsExpression(target) ||
        ts.isSatisfiesExpression(target))
    ) {
      target = target.expression;
    }
    if (target && ts.isObjectLiteralExpression(target)) {
      return target.properties.flatMap((property) =>
        ts.isPropertyAssignment(property)
          ? classFragments(property.initializer, bindings, seen)
          : [],
      );
    }
    return classFragments(target, bindings, seen);
  }
  if (ts.isCallExpression(node)) {
    return node.arguments.flatMap((argument) => classFragments(argument, bindings, seen));
  }
  if (ts.isConditionalExpression(node)) {
    return [
      ...classFragments(node.whenTrue, bindings, seen),
      ...classFragments(node.whenFalse, bindings, seen),
    ];
  }
  if (ts.isBinaryExpression(node)) {
    return [
      ...classFragments(node.left, bindings, seen),
      ...classFragments(node.right, bindings, seen),
    ];
  }
  if (ts.isArrayLiteralExpression(node)) {
    return node.elements.flatMap((element) => classFragments(element, bindings, seen));
  }
  if (ts.isObjectLiteralExpression(node)) {
    return node.properties.flatMap((property) =>
      'name' in property ? classFragments(property.name, bindings, seen) : [],
    );
  }
  if (ts.isJsxExpression(node)) return classFragments(node.expression, bindings, seen);
  return [];
}

function jsxClassData(source, label) {
  const sourceFile = ts.createSourceFile(
    label,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const bindings = staticBindings(sourceFile);
  const entries = [];
  const visit = (node) => {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const classAttribute = node.attributes.properties.find(
        (property) =>
          ts.isJsxAttribute(property) && property.name.getText(sourceFile) === 'className',
      );
      if (classAttribute && ts.isJsxAttribute(classAttribute)) {
        const classes = classAttribute.initializer
          ? classFragments(classAttribute.initializer, bindings).join(' ')
          : '';
        entries.push({
          tag: node.tagName.getText(sourceFile),
          classes,
          line: sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1,
        });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return entries;
}

export function editorialTypographyViolations(source, label, ownsWebsiteEditorialCopy) {
  if (!ownsWebsiteEditorialCopy || !label.endsWith('.tsx')) return [];
  return jsxClassData(source, label)
    .filter((entry) => EDITORIAL_TAGS.has(entry.tag) && EDITORIAL_SIZE.test(entry.classes))
    .map(
      (entry) =>
        label +
        ':' +
        entry.line +
        ': editorial headings and paragraphs must use named website roles',
    );
}

/** Product data absence must name its state instead of rendering punctuation alone. */
export function standalonePlaceholderViolations(source, label, ownsProductUi) {
  if (!ownsProductUi) return [];
  const violations = [];
  const literalStandaloneDash = /(['"`])—\1/g;
  const jsxStandaloneDash = />\s*—\s*</g;
  if (literalStandaloneDash.test(source) || jsxStandaloneDash.test(source)) {
    violations.push(`${label}: standalone em-dash placeholder; use semantic availability copy`);
  }
  return violations;
}

/** Product UI must consume the even type ladder and semantic large-spacing roles. */
export function productUiSourceViolations(source, label, ownsProductUi) {
  if (!ownsProductUi || !label.endsWith('.tsx')) return [];
  const violations = [];
  for (const entry of jsxClassData(source, label)) {
    if (/\btext-5xl\b|\btext-\[[^\]]+\]/.test(entry.classes)) {
      violations.push(`${label}:${entry.line}: product type must use the approved even ladder`);
    }
    if (/\b(?:(?:sm|md|lg|xl):)?(?:gap|p|px|py)-(?:5|6|8)\b/.test(entry.classes)) {
      violations.push(
        `${label}:${entry.line}: product large spacing must use a semantic CSS variable`,
      );
    }
    if (
      /\bwebsite-(?:hero|page|section|feature|small|lead|body|nav|label|eyebrow)/.test(
        entry.classes,
      )
    ) {
      violations.push(`${label}:${entry.line}: product UI must not consume website type roles`);
    }
  }
  return violations;
}

const BUTTON_COLOR_ROLE =
  /^text-(?:foreground|secondary|muted|subtle|accent|danger|success|warning|info|on-|inverse)/;

function cosmeticButtonToken(token) {
  const utility = token.split(':').at(-1) ?? token;
  return (
    utility.startsWith('rounded') ||
    utility.startsWith('bg-') ||
    utility === 'border' ||
    utility.startsWith('border-') ||
    utility.startsWith('shadow') ||
    utility.startsWith('opacity-') ||
    utility.startsWith('scale-') ||
    utility.startsWith('transition') ||
    utility.startsWith('duration-') ||
    utility.startsWith('ease-') ||
    BUTTON_COLOR_ROLE.test(utility)
  );
}

/** Product controls must route behavior and appearance through shared owners. */
const RAW_PRODUCT_CONTROL_MESSAGES = new Map([
  ['select', 'native select must use components/ui/select'],
  ['input', 'raw product input must use a components/ui owner'],
  ['textarea', 'raw product textarea must use components/ui/textarea'],
  ['button', 'raw product button must use Button or Pressable'],
]);

function hasCosmeticButtonOverride(node, sourceFile, bindings) {
  const classAttribute = node.attributes.properties.find(
    (property) => ts.isJsxAttribute(property) && property.name.getText(sourceFile) === 'className',
  );
  if (!classAttribute || !ts.isJsxAttribute(classAttribute)) return false;
  return classFragments(classAttribute.initializer, bindings)
    .join(' ')
    .split(/\s+/)
    .some(cosmeticButtonToken);
}

export function productControlViolations(source, label, ownsProductUi) {
  if (!ownsProductUi || !label.endsWith('.tsx') || label.startsWith('components/ui/')) return [];
  const sourceFile = ts.createSourceFile(
    label,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const bindings = staticBindings(sourceFile);
  const violations = [];
  const visit = (node) => {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText(sourceFile);
      const line = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1;
      const rawControlMessage = RAW_PRODUCT_CONTROL_MESSAGES.get(tag);
      if (rawControlMessage) violations.push(`${label}:${line}: ${rawControlMessage}`);
      if (tag === 'Button' && hasCosmeticButtonOverride(node, sourceFile, bindings)) {
        violations.push(
          `${label}:${line}: Button cosmetics belong in its semantic variant, not className`,
        );
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return violations;
}

export function directRadixImportViolations(source, label) {
  return !label.startsWith('components/ui/') && /from\s+['"]@radix-ui\//.test(source)
    ? [`${label}: feature code must use components/ui instead of importing Radix`]
    : [];
}

/**
 * Tailwind v4 generates EVERY utility family from every theme token, so
 * `--color-subtle` / `--color-muted` / `--color-secondary` (the Gray-500/600/700
 * TEXT inks) silently yield usable `bg-*` utilities. `bg-subtle` painted the
 * page-kind score expansion as a dark slate panel with unreadable controls on
 * it, and neither review nor the type system could catch it.
 *
 * This lived as an ESLint `no-restricted-syntax` selector pair until the linter
 * moved to Oxlint, which does not implement that rule. The check belongs here
 * regardless: it is a design-token contract, and this file already owns the
 * others. The AST walk (rather than a source regex) is what the ESLint
 * selectors gave us -- it matches string and template text only, so the rule
 * cannot be tripped by a prose mention in a comment.
 *
 * NOT banned: `bg-foreground` + `text-background` is the deliberate
 * inverse-chip pattern, and `bg-inverse/70` is a white scrim.
 */
const TEXT_ROLE_BACKGROUND = new RegExp(
  // Assembled from fragments so this policy source -- which the walk in
  // check-design-system.mjs also reads -- can never match itself.
  `(^|\\s)${['bg', '-'].join('')}(subtle|secondary|muted)(\\s|/|$)`,
);

const TEXT_ROLE_BACKGROUND_MESSAGE =
  'background utility built from a TEXT-role token; use a surface token ' +
  '(bg-background-alt, bg-panel, bg-well, bg-elevated, bg-surface-inverse), ' +
  'a border-scale neutral, or a semantic bg-*-bg';

/** Surfaces must never be painted with a text-ink token. */
export function textRoleBackgroundViolations(source, label) {
  if (!/\.(?:tsx|ts|mjs|js)$/.test(label)) return [];
  const sourceFile = ts.createSourceFile(
    label,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const violations = [];
  const visit = (node) => {
    const text =
      ts.isStringLiteralLike(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node)
        ? node.text
        : null;
    if (text !== null && TEXT_ROLE_BACKGROUND.test(text)) {
      const line = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1;
      violations.push(`${label}:${line}: ${TEXT_ROLE_BACKGROUND_MESSAGE}`);
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return violations;
}

function tokenDeclaration(source, token, value) {
  return new RegExp(`${escapeRegExp(token)}\\s*:\\s*${escapeRegExp(value)}\\s*;`).test(source);
}

/** Exact global contract for the spatial/type migration's shared owners. */
export function productContractViolations(root) {
  const violations = [];
  const css = readFileSync(join(root, 'app', 'globals.css'), 'utf8');
  const tokenContract = new Map([
    ['--text-2xs', '0.75rem'],
    ['--text-xs', '0.75rem'],
    ['--text-sm', '0.875rem'],
    ['--text-base', '1rem'],
    ['--text-lg', '1.125rem'],
    ['--text-xl', '1.25rem'],
    ['--text-2xl', '1.5rem'],
    ['--text-3xl', '1.75rem'],
    ['--text-4xl', '2rem'],
    ['--content-gutter', '16px'],
    ['--workspace-gap', '16px'],
    ['--compact-gap', '12px'],
    ['--page-section-gap', '24px'],
    ['--card-padding', '16px'],
    ['--modal-padding', '20px'],
    ['--control-height', '32px'],
    ['--control-height-lg', '36px'],
  ]);
  for (const [token, value] of tokenContract) {
    if (!tokenDeclaration(css, token, value)) {
      violations.push(`app/globals.css: ${token} must equal ${value}`);
    }
  }

  const layout = readFileSync(join(root, 'app', 'layout.tsx'), 'utf8');
  if (!layout.includes('Geist') || !layout.includes("variable: '--font-geist'")) {
    violations.push('app/layout.tsx: Geist must own the shared UI/body font variable');
  }
  if (/\bInter\b|--font-inter/.test(layout + css)) {
    violations.push('app layout/global tokens: Inter must not remain in the font contract');
  }

  const shell = readFileSync(join(root, 'components', 'layout', 'app-shell.tsx'), 'utf8');
  if (!shell.includes('px-[var(--content-gutter)]') || /\b(?:sm|md|lg):p[xy]?-\d/.test(shell)) {
    violations.push('components/layout/app-shell.tsx: shell chrome must own one semantic gutter');
  }
  const alert = readFileSync(join(root, 'components', 'ui', 'alert-variants.ts'), 'utf8');
  if (
    !alert.includes("cva('flex items-start gap-2 text-xs'") ||
    /rounded|\bborder\b|\bp-4\b/.test(alert)
  ) {
    violations.push('components/ui/alert-variants.ts: alerts must remain unboxed inline feedback');
  }
  const table = readFileSync(join(root, 'components', 'ui', 'table.tsx'), 'utf8');
  if (!table.includes('text-xs text-secondary font-medium whitespace-nowrap')) {
    violations.push('components/ui/table.tsx: table headers must be 12px and single-line');
  }
  const eyebrow = readFileSync(join(root, 'components', 'ui', 'eyebrow.tsx'), 'utf8');
  if (
    !eyebrow.includes("export const eyebrowClasses = 'font-sans text-xs font-semibold text-muted';")
  ) {
    violations.push('components/ui/eyebrow.tsx: product eyebrows must be sentence case');
  }
  if (
    !/\.value-placeholder\s*\{[^}]*font-size:\s*var\(--text-xs\);[^}]*font-weight:\s*400;/s.test(
      css,
    )
  ) {
    violations.push(
      'app/globals.css: unavailable values must remain muted 12px regular-weight text',
    );
  }
  return violations;
}

function cssRules(source) {
  const clean = source.replace(/\/\*[\s\S]*?\*\//g, '');
  const rules = [];
  let cursor = 0;
  while (cursor < clean.length) {
    const open = clean.indexOf('{', cursor);
    if (open === -1) break;
    const prelude = clean.slice(cursor, open).trim();
    let depth = 1;
    let close = open + 1;
    while (close < clean.length && depth > 0) {
      if (clean[close] === '{') depth += 1;
      if (clean[close] === '}') depth -= 1;
      close += 1;
    }
    if (depth !== 0) break;
    if (prelude && !prelude.startsWith('@')) {
      rules.push({ prelude, body: clean.slice(open + 1, close - 1) });
    }
    cursor = close;
  }
  return rules;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^$(){}|[\]\\]/g, '\\$&');
}

function declarationPattern(declaration) {
  const separator = declaration.indexOf(':');
  const property = declaration.slice(0, separator).trim();
  const value = declaration.slice(separator + 1).trim();
  return new RegExp(escapeRegExp(property) + '\\s*:\\s*' + escapeRegExp(value) + '\\s*;');
}

function selectorPattern(selector) {
  return new RegExp(escapeRegExp(selector) + '(?![\\w-])');
}

function tokenHex(source, token) {
  const declaration = String.raw`${escapeRegExp(token)}\s*:\s*(#[0-9a-f]{6})\s*(?:;|(?=}))`;
  const match = source.match(new RegExp(declaration, 'i'));
  return match?.[1];
}

function relativeLuminance(hex) {
  const channels = hex
    .slice(1)
    .match(/../g)
    .map((channel) => Number.parseInt(channel, 16) / 255)
    .map((channel) => (channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4));
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrastRatio(first, second) {
  const firstLuminance = relativeLuminance(first);
  const secondLuminance = relativeLuminance(second);
  const lighter = Math.max(firstLuminance, secondLuminance);
  const darker = Math.min(firstLuminance, secondLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

export function textContrastViolations(root) {
  const cssPath = join(root, ...TOKEN_CSS.split('/'));
  const cssLabel = relative(root, cssPath).replaceAll('\\', '/');
  const source = readFileSync(cssPath, 'utf8');
  const tokens = new Map(
    [...LIGHT_SURFACE_TOKENS, ...NEUTRAL_TEXT_TOKENS].map((token) => [
      token,
      tokenHex(source, token),
    ]),
  );
  const violations = [];

  for (const [token, value] of tokens) {
    if (!value) violations.push(`${cssLabel}: ${token} must be a six-digit hex value`);
  }
  if (violations.length) return violations;

  for (const textToken of NEUTRAL_TEXT_TOKENS) {
    for (const surfaceToken of LIGHT_SURFACE_TOKENS) {
      const ratio = contrastRatio(tokens.get(textToken), tokens.get(surfaceToken));
      if (ratio < MINIMUM_NORMAL_TEXT_CONTRAST) {
        violations.push(
          `${cssLabel}: ${textToken} on ${surfaceToken} has ${ratio.toFixed(2)}:1 contrast; ` +
            `${MINIMUM_NORMAL_TEXT_CONTRAST}:1 is required`,
        );
      }
    }
  }

  return violations;
}

export function websiteContractViolations(root) {
  const violations = [];
  const cssPath = join(root, ...WEBSITE_CSS.split('/'));
  const cssLabel = relative(root, cssPath).replaceAll('\\', '/');
  const rules = cssRules(readFileSync(cssPath, 'utf8'));

  for (const [selector, declarations] of CSS_BLOCK_CONTRACTS) {
    const rule = rules.find((candidate) => candidate.prelude.trim() === selector);
    if (!rule) {
      violations.push(cssLabel + ': missing website selector ' + selector);
      continue;
    }
    for (const declaration of declarations) {
      if (!declarationPattern(declaration).test(rule.body)) {
        violations.push(cssLabel + ': ' + selector + ' missing declaration ' + declaration);
      }
    }
  }

  for (const [selector, declaration] of ROLE_COLOR_CONTRACTS) {
    const selectorRegex = selectorPattern(selector);
    const declarationRegex = declarationPattern(declaration);
    if (
      !rules.some((rule) => selectorRegex.test(rule.prelude) && declarationRegex.test(rule.body))
    ) {
      violations.push(cssLabel + ': ' + selector + ' missing scoped declaration ' + declaration);
    }
  }

  for (const [label, roles] of JSX_ROLE_CONTRACTS) {
    const path = join(root, ...label.split('/'));
    const entries = jsxClassData(readFileSync(path, 'utf8'), label);
    for (const role of roles) {
      if (!entries.some((entry) => entry.classes.split(/\s+/).includes(role))) {
        violations.push(label + ': missing website role ' + role + ' on a JSX className');
      }
    }
  }

  return violations;
}
