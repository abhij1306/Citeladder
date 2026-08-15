import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

let pathname = '/site';
let searchParams = new URLSearchParams();
let hasCommerceEvidence = false;

vi.mock('next/navigation', () => ({
  usePathname: () => pathname,
  useSearchParams: () => searchParams,
}));
vi.mock('@/lib/project/project-context', () => ({
  useProjectContext: () => ({ activeProject: { has_commerce_evidence: hasCommerceEvidence } }),
}));

import { MobilePrimaryNavigation, MobileStationNavigation, SidebarNav } from './sidebar-nav';
import { NAV_GROUPS } from './nav-items';

describe('station navigation', () => {
  it('ships the five loop stations and their canonical destinations', () => {
    render(<SidebarNav />);
    expect(NAV_GROUPS.map((group) => group.title)).toEqual([
      'Overview',
      'Analyze',
      'Act',
      'Track',
      'Connect',
    ]);
    expect(screen.getByRole('link', { name: 'Website' })).toHaveAttribute(
      'href',
      '/site?tab=pages',
    );
    expect(screen.getByRole('link', { name: 'Providers' })).toHaveAttribute(
      'href',
      '/settings?tab=providers',
    );
    expect(screen.getByRole('link', { name: 'Prompts' })).toHaveAttribute('href', '/prompts');
    expect(screen.queryByRole('link', { name: 'Growth Agent' })).not.toBeInTheDocument();
  });

  it('hides Commerce without evidence and reveals it when evidence exists', () => {
    const view = render(<SidebarNav />);
    expect(screen.queryByRole('link', { name: 'Commerce' })).not.toBeInTheDocument();
    hasCommerceEvidence = true;
    view.rerender(<SidebarNav />);
    expect(screen.getByRole('link', { name: 'Commerce' })).toHaveAttribute('href', '/products');
    hasCommerceEvidence = false;
  });

  it('uses query-aware active state for settings destinations', () => {
    pathname = '/settings';
    searchParams = new URLSearchParams('tab=providers');
    render(<SidebarNav />);
    expect(screen.getByRole('link', { name: 'Providers' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByRole('link', { name: 'Integrations' })).not.toHaveAttribute(
      'aria-current',
    );
    expect(screen.getByRole('link', { name: 'Settings' })).not.toHaveAttribute('aria-current');
  });

  it('renders exact mobile stations and shared secondary destinations', () => {
    pathname = '/visibility';
    searchParams = new URLSearchParams('tab=trends');
    render(
      <>
        <MobilePrimaryNavigation />
        <MobileStationNavigation />
      </>,
    );
    const primary = screen.getByRole('navigation', { name: 'Primary mobile navigation' });
    expect(primary).toHaveTextContent('OverviewAnalyzeActTrackConnect');
    expect(screen.getByRole('link', { name: 'Track' })).toHaveAttribute('aria-current', 'page');
    const secondary = screen.getByRole('navigation', { name: 'Track destinations' });
    expect(secondary).toHaveTextContent('AI VisibilityRunsAI Referrals');
  });
});
