/** Run the pinned jscpd production ratchet and advisory test scans. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';

const FRONTEND = path.resolve(import.meta.dirname, '..');
const ROOT = path.resolve(FRONTEND, '..');
const BASELINE_PATH = path.join(FRONTEND, 'scripts', 'jscpd-baseline.json');
const CONFIG_PATH = path.join(ROOT, 'jscpd.json');
const BASELINE_REPOSITORY_PATH = 'frontend/scripts/jscpd-baseline.json';
const BIN = process.execPath;
const JSCPD_ENTRYPOINT = path.join(FRONTEND, 'node_modules', 'jscpd', 'run-jscpd.js');
const REVISION = /^(?:HEAD|[0-9a-fA-F]{40})$/;
const EXPECTED_SCOPE = ['backend/app', 'frontend/app', 'frontend/components', 'frontend/lib'];

function normalizeName(value) {
  const reported = String(value);
  const nativePath = reported.startsWith('\\\\?\\') ? reported.slice(4) : reported;
  const absolute = path.resolve(nativePath);
  return path.relative(ROOT, absolute).split(path.sep).join('/');
}

function normalizedCloneContent(source, format) {
  let result = '';
  for (let index = 0; index < source.length;) {
    const current = source[index];
    const next = source[index + 1];
    if (/\s/.test(current)) {
      index += 1;
      continue;
    }
    if (format === 'python' && current === '#') {
      while (index < source.length && source[index] !== '\n') index += 1;
      continue;
    }
    if (format !== 'python' && current === '/' && next === '/') {
      index += 2;
      while (index < source.length && source[index] !== '\n') index += 1;
      continue;
    }
    if (format !== 'python' && current === '/' && next === '*') {
      index += 2;
      while (index < source.length && !(source[index] === '*' && source[index + 1] === '/'))
        index += 1;
      index += 2;
      continue;
    }
    if (current === "'" || current === '"' || (format !== 'python' && current === '`')) {
      const triple = format === 'python' && source.slice(index, index + 3) === current.repeat(3);
      const delimiter = triple ? current.repeat(3) : current;
      result += delimiter;
      index += delimiter.length;
      while (index < source.length) {
        if (source[index] === '\\') {
          result += source.slice(index, index + 2);
          index += 2;
        } else if (source.slice(index, index + delimiter.length) === delimiter) {
          result += delimiter;
          index += delimiter.length;
          break;
        } else {
          result += source[index];
          index += 1;
        }
      }
      continue;
    }
    result += current;
    index += 1;
  }
  return result;
}

function cloneBody(file, format) {
  const reported = String(file.name);
  const nativePath = reported.startsWith('\\\\?\\') ? reported.slice(4) : reported;
  const source = fs
    .readFileSync(path.resolve(nativePath), 'utf8')
    .split(/\r?\n/)
    .slice(file.start - 1, file.end)
    .join('\n');
  return normalizedCloneContent(source, format);
}

export function cloneFingerprint(clone) {
  const occurrences = [clone.firstFile, clone.secondFile]
    .map((file) => normalizeName(file.name))
    .sort();
  const bodies = [
    cloneBody(clone.firstFile, clone.format),
    cloneBody(clone.secondFile, clone.format),
  ].sort();
  const contentHash = createHash('sha256').update(bodies.join('\0')).digest('hex').slice(0, 16);
  return `${clone.format}|${occurrences[0]}|${occurrences[1]}|${contentHash}|${clone.lines}|${clone.tokens}`;
}

function frequencies(values) {
  const result = new Map();
  for (const value of values) result.set(value, (result.get(value) ?? 0) + 1);
  return result;
}

export function validateBaseline(raw) {
  if (
    raw?.format_version !== 1 ||
    raw.tool_version !== '5.0.11' ||
    JSON.stringify(raw.scope) !== JSON.stringify(EXPECTED_SCOPE) ||
    typeof raw.production_percentage !== 'number' ||
    raw.production_percentage < 0 ||
    !Array.isArray(raw.clone_fingerprints) ||
    raw.clone_fingerprints.some((entry) => typeof entry !== 'string')
  ) {
    throw new Error('invalid jscpd baseline');
  }
  return raw;
}

export function readReport(reportPath) {
  if (!fs.existsSync(reportPath)) {
    return { duplicates: [], statistics: { total: { percentage: 0 } } };
  }
  return JSON.parse(fs.readFileSync(reportPath, 'utf8'));
}

function runJscpd(paths, extraArgs = []) {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'citeladder-jscpd-'));
  const args = [
    JSCPD_ENTRYPOINT,
    ...paths,
    '--config',
    CONFIG_PATH,
    '--reporters',
    'json',
    '--output',
    output,
    '--exit-code',
    '0',
    '--silent',
    '--no-colors',
    '--no-gitignore',
    '--absolute',
    ...extraArgs,
  ];
  try {
    const result = spawnSync(BIN, args, {
      cwd: FRONTEND,
      encoding: 'utf8',
      shell: false,
    });
    if (result.error) throw result.error;
    if (result.status !== 0) {
      throw new Error(`jscpd failed (${result.status}): ${result.stderr || result.stdout}`);
    }
    return readReport(path.join(output, 'jscpd-report.json'));
  } finally {
    fs.rmSync(output, { recursive: true, force: true });
  }
}

function baselineAtRevision(revision) {
  if (!REVISION.test(revision)) throw new Error(`invalid base revision: ${revision}`);
  try {
    return validateBaseline(
      JSON.parse(
        execFileSync('git', ['show', `${revision}:${BASELINE_REPOSITORY_PATH}`], {
          cwd: ROOT,
          encoding: 'utf8',
          stdio: ['ignore', 'pipe', 'pipe'],
        }),
      ),
    );
  } catch (error) {
    const detail = `${error?.stderr ?? ''}${error?.message ?? ''}`;
    if (/does not exist in|exists on disk, but not in|path does not exist/i.test(detail))
      return null;
    throw error;
  }
}

export function productionFailures(report, baseline, baseBaseline = null) {
  const failures = [];
  const percentage = Number(report.statistics?.total?.percentage ?? 0);
  const actual = frequencies((report.duplicates ?? []).map(cloneFingerprint));
  const accepted = frequencies(baseline.clone_fingerprints);
  if (percentage > baseline.production_percentage) {
    failures.push(
      `production duplication increased ${baseline.production_percentage}% -> ${percentage}%`,
    );
  }
  for (const [fingerprint, count] of actual) {
    if (count > (accepted.get(fingerprint) ?? 0))
      failures.push(`new production clone: ${fingerprint}`);
  }
  for (const [fingerprint, count] of accepted) {
    if (count > (actual.get(fingerprint) ?? 0))
      failures.push(`stale accepted clone fingerprint: ${fingerprint}`);
  }
  if (baseBaseline) {
    if (
      baseline.format_version !== baseBaseline.format_version ||
      baseline.tool_version !== baseBaseline.tool_version ||
      JSON.stringify(baseline.scope) !== JSON.stringify(baseBaseline.scope)
    ) {
      failures.push('jscpd format, tool version, or scope changed');
    }
    if (baseline.production_percentage > baseBaseline.production_percentage) {
      failures.push('jscpd percentage threshold was relaxed');
    }
    const baseFingerprints = frequencies(baseBaseline.clone_fingerprints);
    for (const [fingerprint, count] of accepted) {
      if (count > (baseFingerprints.get(fingerprint) ?? 0)) {
        failures.push(`new accepted clone fingerprint is forbidden: ${fingerprint}`);
      }
    }
  }
  return failures;
}

function advisoryTestScan() {
  const backend = runJscpd(['../backend/tests'], ['--format', 'python']);
  const frontend = runJscpd(
    ['./app', './components', './lib'],
    ['--format', 'typescript,tsx,javascript,jsx', '--pattern', '**/*.{test,spec}.{ts,tsx,js,jsx}'],
  );
  const backendPercentage = Number(backend.statistics?.total?.percentage ?? 0);
  const frontendPercentage = Number(frontend.statistics?.total?.percentage ?? 0);
  console.log(
    `jscpd test scan advisory: backend ${backendPercentage.toFixed(4)}%, ` +
      `frontend ${frontendPercentage.toFixed(4)}% duplicated lines`,
  );
}

function main() {
  if (process.argv.includes('--tests')) {
    advisoryTestScan();
    return;
  }
  const baseline = validateBaseline(JSON.parse(fs.readFileSync(BASELINE_PATH, 'utf8')));
  const diffIndex = process.argv.indexOf('--check-policy-diff');
  const revision = diffIndex >= 0 ? process.argv[diffIndex + 1] : undefined;
  if (diffIndex >= 0 && !revision) throw new Error('--check-policy-diff requires a revision');
  const report = runJscpd(
    ['../backend/app', './app', './components', './lib'],
    ['--format', 'python,typescript,tsx,javascript,jsx'],
  );
  const failures = productionFailures(
    report,
    baseline,
    revision ? baselineAtRevision(revision) : null,
  );
  if (failures.length) {
    console.error(`jscpd production gate failed:\n- ${failures.join('\n- ')}`);
    process.exitCode = 1;
    return;
  }
  const percentage = Number(report.statistics?.total?.percentage ?? 0);
  console.log(`jscpd production gate passed: ${percentage.toFixed(4)}%`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(import.meta.filename)) main();
