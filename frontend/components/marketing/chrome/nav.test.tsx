import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { DEMO_HREF, NAV_DROPS } from '@/lib/marketing-content/nav';
import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';

import { MarketingNav } from './nav';

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

function stubAnonymous() {
  mswServer.use(
    http.get('/api/v1/auth/me', () =>
      HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 }),
    ),
  );
}

function stubSignedIn() {
  mswServer.use(
    http.get('/api/v1/auth/me', () =>
      HttpResponse.json({
        user: {
          id: '11111111-1111-4111-8111-111111111111',
          email: 'evaluator@example.com',
          role: 'user',
          is_active: true,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      }),
    ),
    http.get('/api/v1/projects', () => HttpResponse.json([])),
  );
}

/**
 * The nav's INTERACTION contract, which survived the Proof rewrite unchanged
 * and is the part most likely to regress silently: hover- and focus-opened
 * dropdowns, Escape to close, truthful `aria-expanded`, and the mobile
 * accordions. The visual system is covered by the design-token suite; this
 * file guards behaviour only.
 */
describe('MarketingNav', () => {
  it('gives every Platform menu row a distinct destination', () => {
    const platform = NAV_DROPS.find((drop) => drop.key === 'platform');
    const hrefs = platform?.groups.flatMap((group) => group.items.map((item) => item.href)) ?? [];

    expect(hrefs).toHaveLength(4);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it('opens a dropdown on hover and on focus, and closes it with Escape', async () => {
    stubAnonymous();
    const user = userEvent.setup();
    renderWithProviders(<MarketingNav />);

    for (const drop of NAV_DROPS) {
      const directLink = screen.getByRole('link', {
        name: new RegExp(`^${drop.label}$`, 'i'),
      });
      expect(directLink).toHaveAttribute('href', drop.href);
      expect(directLink).toHaveAttribute('aria-expanded', 'false');
      expect(document.querySelector(`nav button[aria-label="Open ${drop.label} menu"]`)).toBeNull();

      await user.hover(directLink);
      await waitFor(() => expect(directLink).toHaveAttribute('aria-expanded', 'true'));

      const panel = screen.getByRole('menu');
      expect(panel).toHaveAttribute('id', `desktop-nav-panel-${drop.key}`);
      const expected = drop.groups.reduce((sum, group) => sum + group.items.length, 0);
      expect(within(panel).getAllByRole('menuitem')).toHaveLength(expected);

      await user.keyboard('{Escape}');
      await waitFor(() => expect(directLink).toHaveAttribute('aria-expanded', 'false'));
      await user.unhover(directLink);
    }
  });

  it('keeps the navigation surface transparent until the page scrolls', async () => {
    stubAnonymous();
    renderWithProviders(<MarketingNav />);

    const chrome = document.querySelector<HTMLElement>('[data-marketing-nav]');
    expect(chrome).toHaveClass('bg-transparent', 'border-transparent');

    // `scrollY` is an accessor on the jsdom window, and overriding it with a
    // data property leaks into every later test in the file unless the
    // original descriptor goes back — hence the capture/restore pair.
    const scrollYDescriptor = Object.getOwnPropertyDescriptor(window, 'scrollY');
    try {
      Object.defineProperty(window, 'scrollY', { configurable: true, value: 24 });
      window.dispatchEvent(new Event('scroll'));

      await waitFor(() => expect(chrome).toHaveAttribute('data-scrolled', 'true'));
      expect(chrome).toHaveClass('bg-mkt-surface', 'border-mkt-line-soft');
    } finally {
      if (scrollYDescriptor) {
        Object.defineProperty(window, 'scrollY', scrollYDescriptor);
      } else {
        Reflect.deleteProperty(window, 'scrollY');
      }
      window.dispatchEvent(new Event('scroll'));
    }
  });

  it('exposes every dropdown as a mobile accordion with truthful aria-expanded', async () => {
    stubAnonymous();
    const user = userEvent.setup();
    renderWithProviders(<MarketingNav />);

    await user.click(screen.getByRole('button', { name: 'Open menu' }));
    expect(screen.getByRole('button', { name: 'Close menu' })).toBeInTheDocument();

    for (const drop of NAV_DROPS) {
      // Both the desktop trigger and the accordion head carry the label, so
      // disambiguate on the control the accordion body is wired to.
      const head = document.querySelector<HTMLElement>(`button[aria-controls="acc-${drop.key}"]`);
      expect(head, `accordion head for ${drop.key}`).not.toBeNull();
      expect(head).toHaveAttribute('aria-expanded', 'false');

      await user.click(head!);
      expect(head).toHaveAttribute('aria-expanded', 'true');

      const body = document.querySelector<HTMLElement>(`#acc-${drop.key}`);
      const expected = drop.groups.reduce((sum, group) => sum + group.items.length, 0);
      expect(within(body!).getAllByRole('link')).toHaveLength(expected);
    }

    await user.click(screen.getByRole('button', { name: 'Close menu' }));
    await waitFor(() => expect(document.querySelector('#mobile-menu')).toBeNull());
  });

  it('shows the demo-first CTA and a login link to an anonymous visitor', async () => {
    stubAnonymous();
    renderWithProviders(<MarketingNav />);

    await waitFor(() =>
      expect(screen.getByRole('link', { name: /book a demo/i })).toHaveAttribute('href', DEMO_HREF),
    );
    expect(screen.getByRole('link', { name: /log in/i })).toHaveAttribute('href', '/login');
    // Proof is a light-only identity — a theme toggle here would do nothing.
    expect(screen.queryByRole('button', { name: /toggle color theme/i })).toBeNull();
  });

  it('swaps the CTA for a dashboard link once the session resolves', async () => {
    stubSignedIn();
    renderWithProviders(<MarketingNav />);

    // No projects yet, so the dashboard link routes into first-run onboarding.
    await waitFor(() =>
      expect(screen.getByRole('link', { name: /dashboard/i })).toHaveAttribute(
        'href',
        '/onboarding',
      ),
    );
    expect(screen.queryByRole('link', { name: /book a demo/i })).toBeNull();
  });
});
