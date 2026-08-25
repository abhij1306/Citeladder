import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { COMPETITORS } from '@/lib/marketing-content/compare';
import { DEMO_HREF } from '@/lib/marketing-content/nav';

import { MarketingFooter } from './footer';

/**
 * The footer is a sync server component with no islands, so a plain render is
 * enough. What is worth pinning is the commercial contract: five columns, a
 * Compare column derived from the content module, and — because the repo is
 * private — no GitHub or documentation links anywhere on a commercial page.
 */
describe('MarketingFooter', () => {
  it('renders five labelled columns inside the Footer landmark', () => {
    const { container } = render(<MarketingFooter />);

    expect(container.querySelector('footer')).toHaveClass('bg-active/60');
    const footerNav = screen.getByRole('navigation', { name: 'Footer' });
    expect(within(footerNav).getAllByRole('link').length).toBeGreaterThan(0);
    const headings = container.querySelectorAll('.f-col-label');
    expect(headings).toHaveLength(5);
    for (const heading of headings) {
      expect(heading).toHaveClass('text-foreground', 'font-semibold');
    }
  });

  it('derives the Compare column from the content module', () => {
    render(<MarketingFooter />);

    expect(screen.getByRole('link', { name: 'All comparisons' })).toHaveAttribute(
      'href',
      '/compare',
    );
    for (const competitor of COMPETITORS) {
      expect(screen.getByRole('link', { name: `vs ${competitor.name}` })).toHaveAttribute(
        'href',
        `/compare/${competitor.slug}`,
      );
    }
  });

  it('points the company column at the demo funnel and login', () => {
    render(<MarketingFooter />);

    expect(screen.getByRole('link', { name: /book a demo/i })).toHaveAttribute('href', DEMO_HREF);
    expect(screen.getByRole('link', { name: /log in/i })).toHaveAttribute('href', '/login');
  });

  it('carries no GitHub or documentation links (the repo is private)', () => {
    render(<MarketingFooter />);

    expect(screen.queryByRole('link', { name: /github/i })).toBeNull();
    expect(screen.queryByRole('link', { name: /documentation/i })).toBeNull();
  });

  it('exposes the legal strip with policy links', () => {
    render(<MarketingFooter />);

    const legal = screen.getByRole('navigation', { name: 'Legal' });
    expect(within(legal).getByRole('link', { name: 'Terms of Service' })).toHaveAttribute(
      'href',
      '/terms',
    );
    expect(within(legal).getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute(
      'href',
      '/privacy',
    );
    expect(within(legal).getByRole('link', { name: 'Cookies' })).toHaveAttribute(
      'href',
      '/cookies',
    );
    expect(within(legal).getByRole('link', { name: 'AI Policy' })).toHaveAttribute(
      'href',
      '/ai-policy',
    );
  });
});
