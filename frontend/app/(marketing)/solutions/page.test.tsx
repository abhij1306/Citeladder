import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DEMO_HREF } from '@/lib/marketing-content/nav';

import Page from './page';

// Plain render — the solutions page has no client islands (no providers, no
// MSW). The shared chrome (nav/footer) lives in the route-group layout and is
// covered by colocated component tests + e2e.
describe('Solutions page (public marketing `/solutions`)', () => {
  it('renders exactly one h1 and keeps the product name out of h2-h6', () => {
    render(<Page />);

    const h1s = screen.getAllByRole('heading', { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent(/every team behind the brand/i);

    // No h2-h6 may contain the product name (keeps heading queries unambiguous).
    const headings = screen.getAllByRole('heading');
    for (const heading of headings) {
      if (heading === h1s[0]) continue;
      expect(heading).not.toHaveTextContent(/searchify/i);
    }
  });

  it('centres the hero like the other marketing subpages', () => {
    render(<Page />);

    const h1 = screen.getByRole('heading', { level: 1 });
    expect(h1).toHaveClass('mx-auto');
    expect(h1.closest('.text-center')).not.toBeNull();
    expect(screen.getByRole('navigation', { name: 'Solutions by team' })).toHaveClass(
      'justify-center',
    );
  });

  it('exposes the five segment anchors the nav Solutions dropdown targets', () => {
    const { container } = render(<Page />);

    // The nav dropdown links to `/solutions#<id>` — pin the ids.
    for (const hash of ['#agencies', '#in-house', '#founders', '#commerce', '#pr']) {
      expect(container.querySelector(hash)).not.toBeNull();
    }

    // The hero chip nav points at the same in-page anchors.
    const segNav = screen.getByRole('navigation', { name: 'Solutions by team' });
    for (const hash of ['#agencies', '#in-house', '#founders', '#commerce', '#pr']) {
      const chips = within(segNav).getAllByRole('link');
      expect(chips.some((chip) => chip.getAttribute('href') === hash)).toBe(true);
    }
  });

  it('renders each segment with its key feature mappings and a demo CTA', () => {
    render(<Page />);

    const agencies = screen.getByRole('region', { name: 'Agencies' });
    expect(within(agencies).getByText(/isolated multi-project workspaces/i)).toBeInTheDocument();
    expect(within(agencies).getByText(/authenticated client evidence exports/i)).toBeInTheDocument();
    expect(
      within(agencies).getByRole('link', { name: /see agency workflow/i }),
    ).toHaveAttribute('href', DEMO_HREF);

    const inHouse = screen.getByRole('region', { name: 'In-house teams' });
    expect(within(inHouse).getByText(/multi-engine cross-run trend analysis/i)).toBeInTheDocument();
    expect(within(inHouse).getByText(/33 deterministic site-health rules/i)).toBeInTheDocument();
    expect(within(inHouse).getByText(/Search Console and GA4 syncs/i)).toBeInTheDocument();
    expect(
      within(inHouse).getByRole('link', { name: /see reporting surfaces/i }),
    ).toHaveAttribute('href', DEMO_HREF);

    const founders = screen.getByRole('region', { name: 'Founders' });
    expect(within(founders).getByText(/sample site health crawl/i)).toBeInTheDocument();
    expect(
      within(founders).getByText(/complete data provenance/i),
    ).toBeInTheDocument();
    expect(
      within(founders).getByRole('link', { name: /see first audit sample/i }),
    ).toHaveAttribute('href', DEMO_HREF);

    const commerce = screen.getByRole('region', { name: 'Ecommerce' });
    expect(within(commerce).getAllByText(/price accuracy/i).length).toBeGreaterThan(0);
    expect(within(commerce).getAllByText(/competitor co-placement/i).length).toBeGreaterThan(0);
    expect(
      within(commerce).getByRole('link', { name: /see commerce workflow/i }),
    ).toHaveAttribute('href', DEMO_HREF);

    const pr = screen.getByRole('region', { name: 'PR & communications' });
    expect(within(pr).getByText(/real-time mention and citation tracking/i)).toBeInTheDocument();
    expect(within(pr).getByText(/query fanout tracking/i)).toBeInTheDocument();
    expect(within(pr).getByRole('link', { name: /see citation evidence/i })).toHaveAttribute(
      'href',
      DEMO_HREF,
    );
  });

  it('closes with a CTA band linking to the demo funnel and /pricing', () => {
    render(<Page />);

    const finalCta = screen.getByRole('region', { name: 'Get started' });
    expect(within(finalCta).getByRole('link', { name: /book a demo/i })).toHaveAttribute(
      'href',
      DEMO_HREF,
    );
    expect(within(finalCta).getByRole('link', { name: /see pricing/i })).toHaveAttribute(
      'href',
      '/pricing',
    );
  });
});
