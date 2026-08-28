import { defineConfig } from '@playwright/test';

const e2ePort = 3100;

export default defineConfig({
  testDir: './e2e',
  // The real-stack integration spec owns its own lifecycle + config; run it
  // explicitly with `--config e2e/content-integration.config.ts`. The visual
  // suite has its own config too (`pnpm test:visual`); without this ignore it
  // would show up here as 54 viewport-skipped tests.
  testIgnore: ['**/content-integration.spec.ts', 'visual/**'],
  // One Next dev server compiles routes lazily; serial browser work avoids
  // navigation aborts and hydration races caused by six concurrent compiles.
  workers: 1,
  retries: 1,
  use: {
    baseURL: `http://127.0.0.1:${e2ePort}`,
    trace: 'on-first-retry',
  },
  webServer: {
    command: `pnpm exec next dev -p ${e2ePort} -H 127.0.0.1`,
    url: `http://127.0.0.1:${e2ePort}`,
    reuseExistingServer: !process.env.CI,
  },
});
