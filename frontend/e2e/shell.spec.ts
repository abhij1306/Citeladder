import { expect, test } from '@playwright/test';

import { stubAuthedShell } from './helpers/app-fixture';

/**
 * F5 shell smoke: with an authenticated session the `(app)` shell renders its
 * chrome — sidebar nav groups, the top-bar page title, and the theme
 * toggle. The backend `/auth/me` and `/projects` calls are stubbed at the
 * network layer so the spec does not need a live backend.
 *
 * Note: this requires a running dev server (playwright.config.ts starts one).
 * It is skipped automatically when no browser/dev server is available.
 */
test('authenticated shell renders sidebar groups and top bar', async ({ page }) => {
  // stubAuthedShell supplies the canonical user/project AND the 404 catch-all
  // that keeps unstubbed downstream queries (audits, entitlements) from 401-ing
  // the live backend and bouncing the session to /login.
  await stubAuthedShell(page);

  await page.goto('/visibility');

  // Sidebar groups + a nav item. Scoped to the primary nav landmark and
  // exact-matched so page copy can't satisfy or trip the assertion.
  const nav = page.getByRole('navigation', { name: 'Primary' });
  await expect(nav.getByText('Workspace', { exact: true })).toBeVisible();
  await expect(nav.getByRole('link', { name: 'Site', exact: true })).toBeVisible();
  await expect(nav.getByRole('link', { name: 'Content', exact: true })).toBeVisible();
  await expect(nav.getByRole('link', { name: 'Demand', exact: true })).toBeVisible();

  // Project switcher shows the active brand.
  await expect(page.getByText('Acme').first()).toBeVisible();

  // Page title + theme toggle are present. The v2 Figma shell restores the
  // 52px top bar, and the title is the page's single <h1> inside it; scoping
  // by heading level keeps this independent of the surrounding landmark.
  await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible();
  await expect(page.getByRole('button', { name: /search or jump to/i })).toBeVisible();
});
