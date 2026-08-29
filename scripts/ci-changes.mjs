#!/usr/bin/env node

import { appendFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const TRUE = 'true';
const FALSE = 'false';
const GIT_EXECUTABLE =
  process.platform === 'win32' ? String.raw`C:\Program Files\Git\cmd\git.exe` : '/usr/bin/git';
const DOC_FILES = new Set([
  'CHANGELOG.md',
  'CONTRIBUTING.md',
  'LICENSE',
  'README.md',
  'Review.md',
]);

function isDocumentation(path) {
  return path.startsWith('docs/') || DOC_FILES.has(path);
}

function isBackend(path) {
  return path.startsWith('backend/') || path.startsWith('migrations/') || path === 'reset-db.py';
}

function isFrontend(path) {
  return path.startsWith('frontend/');
}

function isContract(path) {
  return (
    path.startsWith('backend/app/api/') ||
    path === 'backend/app/main.py' ||
    /^backend\/app\/.+\/[^/]*schemas?\.py$/.test(path) ||
    path === 'backend/scripts/export_openapi.py' ||
    path.startsWith('frontend/lib/api/')
  );
}

function isSecuritySensitive(path) {
  return (
    path === '.secrets.baseline' ||
    path === 'backend/pyproject.toml' ||
    path === 'backend/uv.lock' ||
    path === 'frontend/package.json' ||
    path === 'frontend/pnpm-lock.yaml' ||
    path.startsWith('.github/')
  );
}

function isComposeSensitive(path) {
  return (
    path === '.dockerignore' ||
    path === '.env.example' ||
    path === 'Dockerfile' ||
    path.startsWith('docker-compose') ||
    path.startsWith('migrations/') ||
    path === 'backend/pyproject.toml' ||
    path === 'backend/uv.lock' ||
    path === 'frontend/package.json' ||
    path === 'frontend/pnpm-lock.yaml' ||
    path === 'frontend/next.config.ts'
  );
}

export function classifyPaths(paths, { full = false, initial = false } = {}) {
  if (full) {
    return {
      backend: true,
      frontend: true,
      contract: true,
      e2e: true,
      security: true,
      compose: true,
    };
  }

  const normalized = [...new Set(paths.map((path) => path.replaceAll('\\', '/')))];
  const shared = normalized.some(
    (path) => !isDocumentation(path) && !isBackend(path) && !isFrontend(path),
  );
  const contract = shared || normalized.some(isContract);
  const backend = shared || contract || normalized.some(isBackend);
  const frontend = shared || contract || normalized.some(isFrontend);

  return {
    backend,
    frontend,
    contract,
    e2e: shared || normalized.some(isFrontend),
    security: shared || normalized.some(isSecuritySensitive),
    compose:
      normalized.some(isComposeSensitive) ||
      (initial && normalized.some((path) => isBackend(path) || isFrontend(path) || !isDocumentation(path))),
  };
}

export function selectDiff({ eventName, action, beforeSha, baseSha, headSha }) {
  if (eventName !== 'pull_request') return { full: true, initial: false, range: null };

  const usableBefore = beforeSha && !/^0+$/.test(beforeSha);
  if (action === 'synchronize' && usableBefore) {
    return { full: false, initial: false, range: `${beforeSha}..${headSha}` };
  }
  if (!baseSha) throw new Error('CI_BASE_SHA is required for the initial pull-request diff.');
  return { full: false, initial: true, range: `${baseSha}...${headSha}` };
}

function changedPaths(range) {
  if (!range) return [];
  const output = execFileSync(
    GIT_EXECUTABLE,
    ['diff', '--no-renames', '--name-only', '--diff-filter=ACMDT', range],
    { encoding: 'utf8' },
  );
  return output.split(/\r?\n/u).filter(Boolean);
}

export function failedJobOwners(jobs, workflowFile) {
  const owners = new Set();
  const prefixes =
    workflowFile === 'compose-smoke.yml'
      ? [['Clean-clone Compose smoke', 'compose']]
      : [
          ['Backend (quality, pytest)', 'backend'],
          ['Frontend (quality, coverage, build)', 'frontend'],
          ['API contract (backend to frontend)', 'contract'],
          ['E2E (playwright)', 'e2e'],
          ['Security (pip-audit, detect-secrets)', 'security'],
        ];

  for (const job of jobs) {
    const match = prefixes.find(([name]) => job.name === name);
    if (match && !['success', 'skipped'].includes(job.conclusion)) owners.add(match[1]);
  }
  return owners;
}

async function previousFailedOwners(environment) {
  if (environment.GITHUB_EVENT_ACTION !== 'synchronize' || !environment.CI_BEFORE_SHA) {
    return new Set();
  }
  const token = environment.GITHUB_TOKEN;
  const repository = environment.GITHUB_REPOSITORY;
  const workflowFile = environment.CI_WORKFLOW_FILE;
  if (!token || !repository || !workflowFile) return new Set();

  const headers = {
    Accept: 'application/vnd.github+json',
    Authorization: `Bearer ${token}`,
    'X-GitHub-Api-Version': '2022-11-28',
  };
  const runsUrl = new URL(
    `https://api.github.com/repos/${repository}/actions/workflows/${encodeURIComponent(workflowFile)}/runs`,
  );
  runsUrl.searchParams.set('event', 'pull_request');
  runsUrl.searchParams.set('per_page', '30');
  if (environment.CI_HEAD_REF) runsUrl.searchParams.set('branch', environment.CI_HEAD_REF);

  const runsResponse = await fetch(runsUrl, { headers });
  if (!runsResponse.ok) throw new Error(`workflow-runs query returned ${runsResponse.status}`);
  const runs = await runsResponse.json();
  const previous = runs.workflow_runs.find((run) => run.head_sha === environment.CI_BEFORE_SHA);
  if (!previous) return new Set();

  const jobsResponse = await fetch(
    `https://api.github.com/repos/${repository}/actions/runs/${previous.id}/jobs?per_page=100`,
    { headers },
  );
  if (!jobsResponse.ok) throw new Error(`workflow-jobs query returned ${jobsResponse.status}`);
  const jobs = await jobsResponse.json();
  return failedJobOwners(jobs.jobs, workflowFile);
}

export function applyFailedOwners(result, owners) {
  for (const owner of owners) result[owner] = true;
  if (result.contract) result.backend = true;
}

function writeOutputs(result, outputPath) {
  const lines = Object.entries(result).map(([name, enabled]) => `${name}=${enabled ? TRUE : FALSE}`);
  appendFileSync(outputPath, `${lines.join('\n')}\n`, 'utf8');
}

async function main(environment = process.env) {
  const diff = selectDiff({
    eventName: environment.GITHUB_EVENT_NAME,
    action: environment.GITHUB_EVENT_ACTION,
    beforeSha: environment.CI_BEFORE_SHA,
    baseSha: environment.CI_BASE_SHA,
    headSha: environment.CI_HEAD_SHA,
  });
  const paths = changedPaths(diff.range);
  const result = classifyPaths(paths, diff);

  try {
    applyFailedOwners(result, await previousFailedOwners(environment));
  } catch (error) {
    process.stderr.write(`Unable to read the previous CI result; running every owner: ${error.message}\n`);
    for (const owner of Object.keys(result)) result[owner] = true;
  }

  process.stdout.write(
    `CI diff: ${diff.full ? 'full main validation' : diff.range}; ${paths.length} changed path(s)\n`,
  );
  process.stdout.write(`${JSON.stringify(result)}\n`);
  if (!environment.GITHUB_OUTPUT) throw new Error('GITHUB_OUTPUT is required.');
  writeOutputs(result, environment.GITHUB_OUTPUT);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
