import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({
  usePathname: () => '/site',
}));

import { SidebarNav } from './sidebar-nav';
import { NAV_GROUPS } from './nav-items';

function renderNav() {
  return render(<SidebarNav />);
}

/**
 * The sidebar IS the architecture (§4): flat, six destinations, no verb
 * grouping. These tests pin that shape, because the failure mode is drift back
 * toward a verb-grouped tree that cuts across the four layers.
 */
describe('SidebarNav', () => {
  it('is flat — one group, so navigation stays two levels deep', () => {
    renderNav();
    expect(NAV_GROUPS).toHaveLength(1);
  });

  it('names the four layers plus Commerce and Reports', () => {
    renderNav();
    const labels = NAV_GROUPS.flatMap((group) => group.items.map((item) => item.label));
    expect(labels).toEqual(['Overview', 'Site', 'Content', 'Demand', 'Commerce', 'Reports']);
    for (const label of labels) {
      expect(screen.getByRole('link', { name: new RegExp(label, 'i') })).toBeInTheDocument();
    }
  });

  it('carries no verb grouping', () => {
    renderNav();
    // The old model grouped by verb, which cut across the architecture.
    for (const group of ['Analyze', 'Resolve', 'Improve']) {
      expect(screen.queryByText(group)).not.toBeInTheDocument();
    }
  });

  it('drops Issues and Recommended actions as destinations', () => {
    renderNav();
    // §4: findings are insights attached to the artifact they concern,
    // surfaced in their owning layer — not a standalone inbox.
    expect(screen.queryByRole('link', { name: /^issues$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /recommended actions/i })).not.toBeInTheDocument();
  });

  it('renders items as navigable links', () => {
    renderNav();
    expect(screen.getByRole('link', { name: /^site$/i })).toHaveAttribute('href', '/site');
    expect(screen.getByRole('link', { name: /^demand$/i })).toHaveAttribute('href', '/demand');
  });

  it('highlights the active route', () => {
    renderNav();
    expect(screen.getByRole('link', { name: /^site$/i })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: /^content$/i })).not.toHaveAttribute('aria-current');
  });

  it('renders every item as a link — no disabled state or "soon" badge', () => {
    renderNav();
    const links = screen.getAllByRole('link');
    expect(links).toHaveLength(6);
    for (const link of links) {
      expect(link).not.toHaveAttribute('aria-disabled');
    }
    expect(screen.queryByText(/soon/i)).not.toBeInTheDocument();
  });
});
