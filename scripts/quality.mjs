#!/usr/bin/env node

import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const backendRoot = join(repositoryRoot, 'backend');
const frontendRoot = join(repositoryRoot, 'frontend');
const args = process.argv.slice(2).filter((argument) => argument !== '--');

function option(name, fallback) {
  const separateIndex = args.indexOf(name);
  if (separateIndex >= 0) return args[separateIndex + 1] ?? fallback;
  const inline = args.find((argument) => argument.startsWith(`${name}=`));
  return inline?.slice(name.length + 1) ?? fallback;
}

const mode = option('--mode', 'fix');
if (!['fix', 'check'].includes(mode)) throw new Error(`Unknown quality mode: ${mode}`);

const requestedScopes = option('--scope', 'all')
  .split(',')
  .map((scope) => scope.trim().toLowerCase());
const validScopes = new Set(['all', 'backend', 'frontend', 'docs', 'contract']);
for (const scope of requestedScopes) {
  if (!validScopes.has(scope)) throw new Error(`Unknown quality scope: ${scope}`);
}
const scopes = requestedScopes.includes('all')
  ? new Set(['backend', 'frontend', 'docs', 'contract'])
  : new Set(requestedScopes);

function executable(candidates, missingMessage) {
  const path = candidates.find(existsSync);
  if (!path) throw new Error(missingMessage);
  return path;
}

const backendPython = () =>
  executable(
    [join(backendRoot, '.venv', 'Scripts', 'python.exe'), join(backendRoot, '.venv', 'bin', 'python')],
    "Backend virtual environment missing. Run 'uv sync --frozen --extra dev' in backend/.",
  );

function backendTool(name) {
  return executable(
    [join(backendRoot, '.venv', 'Scripts', `${name}.exe`), join(backendRoot, '.venv', 'bin', name)],
    `Backend tool '${name}' missing. Run 'uv sync --frozen --extra dev' in backend/.`,
  );
}

function step(name, command, commandArgs, cwd, env = process.env) {
  process.stdout.write(`\n==> ${name}\n`);
  const result = spawnSync(command, commandArgs, {
    cwd,
    env,
    stdio: 'inherit',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

function pnpm(name, commandArgs) {
  if (process.platform === 'win32') {
    step(name, process.env.ComSpec ?? 'cmd.exe', ['/d', '/s', '/c', 'pnpm', ...commandArgs], frontendRoot);
    return;
  }
  step(name, 'pnpm', commandArgs, frontendRoot);
}

function policyDiffArgs() {
  const base = process.env.COMPLEXITY_BASE_SHA;
  return base && !/^0+$/.test(base) ? ['--', '--check-policy-diff', base] : [];
}

function backendChecks() {
  const rootScripts = [
    '--config',
    'pyproject.toml',
    '../reset-db.py',
    '../docs/validate_documentation.py',
  ];
  if (mode === 'check') {
    step('Ruff lint', backendTool('ruff'), ['check', '.', ...rootScripts], backendRoot);
    step('Ruff format', backendTool('ruff'), ['format', '--check', '.', ...rootScripts], backendRoot);
  } else {
    step('Ruff lint fixes', backendTool('ruff'), ['check', '.', '--fix', ...rootScripts], backendRoot);
    step('Ruff format fixes', backendTool('ruff'), ['format', '.', ...rootScripts], backendRoot);
  }
  step('Mypy', backendTool('mypy'), [], backendRoot);
  step(
    'Complexity policy',
    backendPython(),
    ['-m', 'scripts.check_complexity', ...policyDiffArgs().slice(1)],
    backendRoot,
  );
  step('Architecture policy', backendTool('lint-imports'), [], backendRoot);
  step(
    'Dead-code policy',
    backendTool('vulture'),
    ['app', 'evaluations', 'scripts', '--min-confidence', '80'],
    backendRoot,
  );
  step('Dependency hygiene', backendTool('deptry'), ['.'], backendRoot);
}

function frontendChecks() {
  pnpm(mode === 'check' ? 'Oxfmt format' : 'Oxfmt format fixes', [
    mode === 'check' ? 'format:check' : 'format',
  ]);
  pnpm('Oxlint', ['lint']);
  pnpm('TypeScript', ['exec', 'tsc', '--noEmit']);
  pnpm('Frontend complexity policy', ['check:complexity', ...policyDiffArgs()]);
  pnpm('Duplication policy', ['check:duplicates', ...policyDiffArgs()]);
  pnpm('Design-system and architecture policy', ['check:policy']);
  pnpm('Frontend dead-code and dependency policy', ['check:dead-code']);
}

if (scopes.has('backend')) backendChecks();
if (scopes.has('frontend')) frontendChecks();
if (scopes.has('docs')) {
  step('Documentation index', backendPython(), ['docs/validate_documentation.py'], repositoryRoot);
}
if (scopes.has('contract')) pnpm('API contract policy', ['check:contract']);

process.stdout.write(`\n${[...scopes].join(', ')} quality ${mode} passed.\n`);
