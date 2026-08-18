/** Enforce the frontend CC/LOC ratchet and reject policy relaxation. */
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import ts from 'typescript';

const FRONTEND = path.resolve(import.meta.dirname, '..');
const REPOSITORY = path.resolve(FRONTEND, '..');
const POLICY_PATH = path.join(FRONTEND, 'scripts', 'frontend_complexity_policy.json');
const POLICY_REPOSITORY_PATH = 'frontend/scripts/frontend_complexity_policy.json';
const EXPECTED_ROOTS = ['app', 'components', 'lib'];
const REVISION = /^(?:HEAD|[0-9a-fA-F]{40})$/;
const FUNCTION_KINDS = new Set([
  ts.SyntaxKind.FunctionDeclaration,
  ts.SyntaxKind.FunctionExpression,
  ts.SyntaxKind.ArrowFunction,
  ts.SyntaxKind.MethodDeclaration,
  ts.SyntaxKind.Constructor,
  ts.SyntaxKind.GetAccessor,
  ts.SyntaxKind.SetAccessor,
]);
const BRANCH_KINDS = new Set([
  ts.SyntaxKind.IfStatement,
  ts.SyntaxKind.ForStatement,
  ts.SyntaxKind.ForInStatement,
  ts.SyntaxKind.ForOfStatement,
  ts.SyntaxKind.WhileStatement,
  ts.SyntaxKind.DoStatement,
  ts.SyntaxKind.CatchClause,
  ts.SyntaxKind.ConditionalExpression,
  ts.SyntaxKind.CaseClause,
  ts.SyntaxKind.DefaultClause,
]);

function isFunction(node) {
  return FUNCTION_KINDS.has(node.kind);
}
function cyclomatic(node) {
  let score = 1;
  function visit(child) {
    if (child !== node && isFunction(child)) return;
    if (BRANCH_KINDS.has(child.kind)) score += 1;
    if (
      child.kind === ts.SyntaxKind.BinaryExpression &&
      [
        ts.SyntaxKind.AmpersandAmpersandToken,
        ts.SyntaxKind.BarBarToken,
        ts.SyntaxKind.QuestionQuestionToken,
      ].includes(child.operatorToken.kind)
    )
      score += 1;
    ts.forEachChild(child, visit);
  }
  ts.forEachChild(node, visit);
  return score;
}
function displayName(node, sourceFile, line, column) {
  if (node.name?.getText) return node.name.getText(sourceFile);
  if (node.parent?.name?.getText)
    return `${node.parent.name.getText(sourceFile)}::<anonymous>@${line}:${column}`;
  return `<anonymous>@${line}:${column}`;
}
function filesUnder(root) {
  const result = [];
  function visit(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      if (
        ['node_modules', '.next', 'out', 'coverage', 'playwright-report', 'test-results'].includes(
          entry.name,
        )
      )
        continue;
      const absolute = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(absolute);
      else if (/\.(?:ts|tsx|js|jsx)$/.test(entry.name) && !/\.d\.ts$/.test(entry.name))
        result.push(absolute);
    }
  }
  visit(root);
  return result.sort();
}
function isTestFile(file) {
  return (
    /(?:\.test|\.spec)\.(?:ts|tsx|js|jsx)$/.test(file) || file.split(path.sep).includes('__tests__')
  );
}

export function measure(file) {
  const source = fs.readFileSync(file, 'utf8');
  const scriptKind = /\.tsx$/.test(file)
    ? ts.ScriptKind.TSX
    : /\.jsx$/.test(file)
      ? ts.ScriptKind.JSX
      : ts.ScriptKind.TS;
  const sourceFile = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, scriptKind);
  const functions = [];
  function visit(node) {
    if (isFunction(node)) {
      const position = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
      const line = position.line + 1;
      const column = position.character + 1;
      functions.push({
        name: displayName(node, sourceFile, line, column),
        cc: cyclomatic(node),
        line,
      });
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return { loc: source.split(/\r?\n/).length, test: isTestFile(file), functions };
}

export function validatePolicy(policy) {
  if (
    !policy ||
    Object.keys(policy).sort().join(',') !== 'defaults,exceptions,format_version,roots' ||
    policy.format_version !== 1
  )
    throw new Error('invalid frontend complexity policy shape');
  if (JSON.stringify(policy.roots) !== JSON.stringify(EXPECTED_ROOTS))
    throw new Error('policy roots must remain app, components, lib');
  const defaults = policy.defaults;
  if (
    !defaults ||
    Object.keys(defaults).sort().join(',') !== 'max_function_cc,max_production_loc,max_test_loc' ||
    defaults.max_function_cc !== 12 ||
    defaults.max_production_loc !== 500 ||
    defaults.max_test_loc !== 800
  )
    throw new Error('frontend complexity defaults must remain CC 12, production 500, test 800 LOC');
  const exceptions = policy.exceptions;
  if (
    !exceptions ||
    Object.keys(exceptions).sort().join(',') !== 'functions,modules' ||
    !exceptions.functions ||
    !exceptions.modules ||
    Array.isArray(exceptions.functions) ||
    Array.isArray(exceptions.modules)
  )
    throw new Error('policy exceptions must contain function and module maps');
  for (const [kind, entries] of Object.entries(exceptions))
    for (const [name, ceiling] of Object.entries(entries)) {
      if (!name || typeof ceiling !== 'number' || !Number.isInteger(ceiling) || ceiling <= 0)
        throw new Error(`invalid ${kind} exception: ${name}`);
      const minimum =
        kind === 'functions'
          ? defaults.max_function_cc
          : Math.min(defaults.max_production_loc, defaults.max_test_loc);
      if (ceiling <= minimum) throw new Error(`${kind} exception ${name} must exceed its default`);
    }
  return policy;
}
export function loadPolicy(file = POLICY_PATH) {
  return validatePolicy(JSON.parse(fs.readFileSync(file, 'utf8')));
}
export function collect(policy) {
  const measurements = {};
  for (const root of policy.roots)
    for (const file of filesUnder(path.join(FRONTEND, root)))
      measurements[path.relative(FRONTEND, file).split(path.sep).join('/')] = measure(file);
  return measurements;
}
export function failuresFor(measurements, policy) {
  const failures = [];
  for (const [file, measurement] of Object.entries(measurements)) {
    const ceiling =
      policy.exceptions.modules[file] ??
      (measurement.test ? policy.defaults.max_test_loc : policy.defaults.max_production_loc);
    if (measurement.loc > ceiling)
      failures.push(`${file}: LOC ${measurement.loc} exceeds ceiling ${ceiling}`);
    for (const fn of measurement.functions) {
      const functionCeiling =
        policy.exceptions.functions[`${file}::${fn.name}`] ?? policy.defaults.max_function_cc;
      if (fn.cc > functionCeiling)
        failures.push(`${file}::${fn.name}: CC ${fn.cc} exceeds ceiling ${functionCeiling}`);
    }
  }
  return failures;
}
export function staleExceptionFailures(measurements, policy) {
  const failures = [];
  for (const file of Object.keys(policy.exceptions.modules)) {
    const measurement = measurements[file];
    if (!measurement) failures.push(`stale module exception: ${file} does not exist`);
    else if (
      measurement.loc <=
      (measurement.test ? policy.defaults.max_test_loc : policy.defaults.max_production_loc)
    )
      failures.push(`stale module exception: ${file} is now within the default`);
  }
  for (const key of Object.keys(policy.exceptions.functions)) {
    const separator = key.lastIndexOf('::');
    const measurement = measurements[key.slice(0, separator)];
    const name = key.slice(separator + 2);
    const fn = measurement?.functions.find((candidate) => candidate.name === name);
    if (!fn) failures.push(`stale function exception: ${key} does not exist`);
    else if (fn.cc <= policy.defaults.max_function_cc)
      failures.push(`stale function exception: ${key} is now within the default`);
  }
  return failures;
}
export function policyDiffFailures(base, current) {
  validatePolicy(base);
  validatePolicy(current);
  const failures = [];
  if (JSON.stringify(base.roots) !== JSON.stringify(current.roots))
    failures.push('application roots changed');
  for (const key of ['max_function_cc', 'max_production_loc', 'max_test_loc'])
    if (current.defaults[key] > base.defaults[key])
      failures.push(`default ${key} increased ${base.defaults[key]} -> ${current.defaults[key]}`);
  for (const kind of ['functions', 'modules'])
    for (const [name, value] of Object.entries(current.exceptions[kind])) {
      if (!(name in base.exceptions[kind]))
        failures.push(`new ${kind.slice(0, -1)} exception is forbidden: ${name}`);
      else if (value > base.exceptions[kind][name])
        failures.push(
          `${kind.slice(0, -1)} exception ${name} increased ${base.exceptions[kind][name]} -> ${value}`,
        );
    }
  return failures;
}
function policyAtRevision(revision) {
  if (!REVISION.test(revision)) throw new Error(`invalid base revision: ${revision}`);
  return JSON.parse(
    execFileSync('git', ['show', `${revision}:${POLICY_REPOSITORY_PATH}`], {
      cwd: REPOSITORY,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    }),
  );
}
export function main() {
  const baseIndex = process.argv.indexOf('--check-policy-diff');
  if (baseIndex >= 0 && !process.argv[baseIndex + 1])
    throw new Error('--check-policy-diff requires a revision');
  const policy = loadPolicy();
  const measurements = collect(policy);
  const failures = [
    ...failuresFor(measurements, policy),
    ...staleExceptionFailures(measurements, policy),
  ];
  if (baseIndex >= 0) {
    try {
      failures.push(...policyDiffFailures(policyAtRevision(process.argv[baseIndex + 1]), policy));
    } catch (error) {
      const detail = `${error?.stderr ?? ''}${error?.message ?? error}`;
      if (
        !/does not exist in|exists on disk, but not in|path does not exist|pathspec/i.test(detail)
      )
        throw error;
    }
  }
  if (failures.length) {
    console.error(`frontend complexity policy failed (${failures.length}):`);
    for (const failure of failures) console.error(`  - ${failure}`);
    process.exitCode = 1;
  } else console.log(`frontend complexity policy ok (${Object.keys(measurements).length} modules)`);
}
if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(import.meta.filename)) main();
