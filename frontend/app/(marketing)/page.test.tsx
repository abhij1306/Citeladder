import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';

import { queryKeys } from '@/lib/api/query-keys';
import { DEMO_HREF } from '@/lib/marketing-content/nav';
import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';

const replace = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn(), refresh: vi.fn() }),
}));

import Page from './page';

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  mswServer.resetHandlers();
  replace.mockReset();
});
afterAll(() => mswServer.close());

/** Anonymous visitor: the session check 401s and the island stays inert. */
function stubAnonymous() {
  mswServer.use(
    http.get('/api/v1/auth/me', () =>
      HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 }),
    ),
  );
}

// Landing content only. The shared chrome (aurora/grain backdrop, LandingNav,
// LandingFooter) moved into the (marketing) route-group layout, whose
// next/font import makes direct layout renders impractical in vitest — the
// nav/footer contracts get colocated component tests and the layout
// composition is covered by e2e. The LandingSessionRedirect island itself is
// covered exhaustively in components/marketing/landing-session-redirect.test.tsx.
describe('Landing page (public marketing `/`)', () => {
  it('renders exactly one h1 and keeps the marketing content up after the 401 settles', async () => {
    stubAnonymous();
    const { queryClient } = renderWithProviders(<Page />);

    const h1s = screen.getAllByRole('heading', { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent(/see your market through/i);

    // No h2-h6 may contain the product name (keeps heading queries unambiguous).
    const headings = screen.getAllByRole('heading');
    for (const heading of headings) {
      if (heading === h1s[0]) continue;
      expect(heading).not.toHaveTextContent(/searchify/i);
    }

    // The session-check island stays inert for an anonymous visitor: the 401
    // settles, no redirect fires, and the content never leaves the screen.
    await waitFor(() =>
      expect(queryClient.getQueryState(queryKeys.auth.me())?.status).toBe('error'),
    );
    expect(replace).not.toHaveBeenCalled();
    expect(h1s[0]).toBeInTheDocument();
  });

  it('exposes the section anchors the shared chrome links to', () => {
    stubAnonymous();
    const { container } = renderWithProviders(<Page />);

    // The nav/footer (rendered by the layout) target these ids — pin them.
    for (const hash of ['#how-it-works', '#platform', '#evidence', '#why']) {
      expect(container.querySelector(hash)).not.toBeNull();
    }
  });

  it('closes with a FinalCta section pointing at the demo funnel', () => {
    stubAnonymous();
    renderWithProviders(<Page />);

    const finalCta = screen.getByRole('region', { name: 'Get started' });
    const cta = within(finalCta).getByRole('link', { name: /book a demo/i });
    expect(cta).toHaveAttribute('href', DEMO_HREF);
  });

  it('keeps the evaluation-gating note and scene artifact ids off the page', () => {
    stubAnonymous();
    renderWithProviders(<Page />);

    expect(screen.queryByText(/limited workspace/i)).toBeNull();
    for (const id of ['09F3C21E', '1A64D0BC', '3E92BA71']) {
      expect(screen.queryByText(id)).toBeNull();
    }
  });

  it('keeps illustrative scene figures out of the page copy', () => {
    stubAnonymous();
    const { container } = renderWithProviders(<Page />);

    // Every scene number is example data, so it must sit inside an
    // aria-hidden subtree carrying a visible "Example data" mark. A figure
    // leaking into real copy would read as a customer result.
    expect(screen.getAllByText(/example data/i).length).toBeGreaterThan(0);
    for (const node of Array.from(container.querySelectorAll('*'))) {
      if (node.children.length > 0 || !/\b(72\.4|1,248|3,091)\b/.test(node.textContent ?? '')) {
        continue;
      }
      expect(
        node.closest('[aria-hidden="true"]'),
        `${node.textContent} is not aria-hidden`,
      ).not.toBeNull();
    }
  });

  it('keeps the first screen text-only and places the workspace directly after it', () => {
    stubAnonymous();
    const { container } = renderWithProviders(<Page />);

    const hero = container.querySelector('header');
    const main = container.querySelector('main');
    expect(hero).not.toBeNull();
    expect(hero).not.toHaveTextContent(/your ai visibility|tracking your brand/i);
    expect(main?.children[0]).toBe(hero);
    expect(main?.children[1]).toHaveAttribute('id', 'platform');
  });

  it('presents strategy as one question-to-action workflow', () => {
    stubAnonymous();
    renderWithProviders(<Page />);

    expect(screen.getByText('From buyer question to next best action.')).toBeInTheDocument();
    expect(screen.getByText('01 / Buyer question')).toBeInTheDocument();
    expect(screen.getByText('02 / Observed pattern')).toBeInTheDocument();
    expect(screen.getByText('03 / Next action')).toBeInTheDocument();
    expect(screen.queryByText(/less like a dashboard making claims/i)).toBeNull();
  });
});
