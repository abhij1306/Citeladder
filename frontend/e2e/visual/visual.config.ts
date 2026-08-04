import { defineConfig, devices } from '@playwright/test';

const viewports = [
  ['desktop-wide', { width: 1440, height: 900 }],
  ['desktop', { width: 1280, height: 800 }],
  ['tablet-landscape', { width: 1024, height: 768 }],
  ['tablet-portrait', { width: 768, height: 1024 }],
  ['mobile', { width: 390, height: 844 }],
  ['mobile-small', { width: 360, height: 800 }],
] as const;
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? `http://127.0.0.1:${process.env.PORT ?? '3000'}`;

export default defineConfig({
  testDir: '.',
  snapshotPathTemplate: '{testDir}/__screenshots__/{testFilePath}/{arg}-{projectName}{ext}',
  expect: { toHaveScreenshot: { animations: 'disabled', maxDiffPixelRatio: 0.01 } },
  projects: viewports.map(([name, viewport]) => ({
    name,
    use: { ...devices['Desktop Chrome'], viewport },
  })),
  use: { baseURL, colorScheme: 'light' },
  webServer: {
    command: 'pnpm dev',
    url: baseURL,
    reuseExistingServer: !process.env.CI,
  },
});
