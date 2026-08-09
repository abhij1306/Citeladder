import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: '*.visual.spec.ts',
  workers: 1,
  retries: 0,
  expect: { toHaveScreenshot: { animations: 'disabled', caret: 'hide' } },
  use: {
    baseURL: 'http://127.0.0.1:3001',
    viewport: { width: 1440, height: 1000 },
  },
  webServer: {
    command: 'pnpm --dir ../.. exec next dev -p 3001',
    url: 'http://127.0.0.1:3001',
    reuseExistingServer: !process.env.CI,
  },
});
