#!/usr/bin/env node
/**
 * `pnpm check:contract` entry point.
 *
 * Runs the same vitest file as `pnpm test` does, but with
 * `CITELADDER_CONTRACT_STRICT=1` so a missing OpenAPI source FAILS instead of
 * skipping (see `lib/api/contract-drift.ts` → `contractGuardIsStrict`). The
 * script exists because the npm script previously invoked vitest directly:
 * that made `check:contract` byte-identical to the wrapper it was documented
 * to differ from, so the guard could silently no-op in CI.
 *
 * Plain node (no `cross-env` dependency) so the env var is set the same way on
 * Windows and POSIX — matching the other `scripts/*.mjs` guards.
 */
import { spawnSync } from 'node:child_process';

const result = spawnSync(
  'vitest',
  ['run', 'lib/api/contract-drift.test.ts', ...process.argv.slice(2)],
  {
    stdio: 'inherit',
    shell: true,
    env: { ...process.env, CITELADDER_CONTRACT_STRICT: '1' },
  },
);

process.exit(result.status ?? 1);
