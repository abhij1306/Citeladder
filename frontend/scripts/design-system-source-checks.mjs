import { readFileSync } from 'node:fs';
import { join, relative } from 'node:path';

import ts from 'typescript';

const EDITORIAL_TAGS = new Set(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p']);
const EDITORIAL_SIZE = /\btext-(?:2xs|xs|sm|base|lg|xl|2xl|3xl|4xl|5xl)\b/;
const WEBSITE_CSS = 'app/website-type.css';

const CSS_BLOCK_CONTRACTS = new Map([
  ['.website-hero-display', ['font-size: 2.75rem', 'letter-spacing: -0.04em']],
  ['.website-page-title', ['font-size: 2.5rem', 'letter-spacing: -0.035em']],
  ['.website-section-heading', []],
  ['.website-feature-heading', []],
  ['.website-small-heading', []],
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
  ['components/auth/auth-form.tsx', ['website-small-heading', 'website-body']],
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
