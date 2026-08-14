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

describe('SidebarNav', () => {
  it('groups primary workspaces under the three intelligence systems', () => {
    renderNav();
    expect(NAV_GROUPS.map((group) => group.title)).toEqual([
      'Workspace',
      'Site Health',
      'Content Intelligence',
      'Demand Intelligence',
    ]);
  });

  it('keeps the primary workspaces directly reachable', () => {
    renderNav();
    const labels = NAV_GROUPS.flatMap((group) => group.items.map((item) => item.label));
    expect(labels).toEqual([
      'Overview',
      'Growth Agent',
      'Website',
      'Issues',
      'Opportunities',
      'Facts',
      'Content',
      'Search Demand',
      'AI Visibility',
      'AI Referrals',
      'Traffic',
      'Prompts',
      'Commerce',
      'Runs',
    ]);
    for (const label of labels) {
      expect(screen.getByRole('link', { name: new RegExp(`^${label}$`, 'i') })).toBeInTheDocument();
    }
  });

  it('carries no verb grouping', () => {
    renderNav();
    // The old model grouped by verb, which cut across the architecture.
    for (const group of ['Analyze', 'Resolve', 'Improve']) {
      expect(screen.queryByText(group)).not.toBeInTheDocument();
    }
  });

  it('renders items as navigable links', () => {
    renderNav();
    expect(screen.getByRole('link', { name: /^website$/i })).toHaveAttribute('href', '/site');
    expect(screen.getByRole('link', { name: /^search demand$/i })).toHaveAttribute(
      'href',
      '/demand',
    );
  });

  it('highlights the active route', () => {
    renderNav();
    expect(screen.getByRole('link', { name: /^website$/i })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByRole('link', { name: /^content$/i })).not.toHaveAttribute('aria-current');
  });

  it('renders every item as a link — no disabled state or "soon" badge', () => {
    renderNav();
    const links = screen.getAllByRole('link');
    expect(links).toHaveLength(14);
    for (const link of links) {
      expect(link).not.toHaveAttribute('aria-disabled');
    }
    expect(screen.queryByText(/soon/i)).not.toBeInTheDocument();
  });
});
