import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

let pathname = '/site';
let searchParams = new URLSearchParams();

vi.mock('next/navigation', () => ({
  usePathname: () => pathname,
  useSearchParams: () => searchParams,
}));

import { MobilePrimaryNavigation, MobileStationNavigation, SidebarNav } from './sidebar-nav';
import { NAV_GROUPS } from './nav-items';

describe('station navigation', () => {
  it('ships the four loop stations and their canonical destinations', () => {
    render(<SidebarNav />);
    expect(NAV_GROUPS.map((group) => group.title)).toEqual(['Overview', 'Analyze', 'Act', 'Track']);
    expect(screen.getByRole('link', { name: 'Website' })).toHaveAttribute(
      'href',
      '/site?tab=pages',
    );
    expect(screen.getByRole('link', { name: 'Opportunities' })).toHaveAttribute(
      'href',
      '/opportunities',
    );
    expect(screen.getByRole('link', { name: 'Commerce Suite' })).toHaveAttribute(
      'href',
      '/products',
    );
    expect(screen.getByRole('link', { name: 'Prompts' })).toHaveAttribute('href', '/prompts');
    expect(screen.queryByRole('link', { name: 'Growth Agent' })).not.toBeInTheDocument();
  });

  it('uses query-aware active state for station destinations', () => {
    pathname = '/site';
    searchParams = new URLSearchParams('tab=pages');
    render(<SidebarNav />);
    expect(screen.getByRole('link', { name: 'Website' })).toHaveAttribute('aria-current', 'page');
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
    expect(primary).toHaveTextContent('OverviewAnalyzeActTrack');
    expect(screen.getByRole('link', { name: 'Track' })).toHaveAttribute('aria-current', 'page');
    const secondary = screen.getByRole('navigation', { name: 'Track destinations' });
    expect(secondary).toHaveTextContent('PromptsAI VisibilityRunsAI Referrals');
  });

  it('omits section heading for Overview but renders headings for other stations', () => {
    render(<SidebarNav />);
    expect(screen.queryByText('Overview', { selector: 'p' })).not.toBeInTheDocument();
    expect(screen.getByText('Analyze', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByText('Act', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByText('Track', { selector: 'p' })).toBeInTheDocument();
    expect(screen.queryByText('Connect', { selector: 'p' })).not.toBeInTheDocument();
  });
});
