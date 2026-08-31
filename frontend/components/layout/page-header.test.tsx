import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const { pathname } = vi.hoisted(() => ({ pathname: { value: '/visibility' } }));

vi.mock('next/navigation', () => ({
  usePathname: () => pathname.value,
}));

import { PageHeader } from './page-header';

function renderTitle(route: string) {
  pathname.value = route;
  render(<PageHeader />);
  return screen.getByRole('heading', { level: 1 }).textContent;
}

describe('PageHeader', () => {
  it.each([
    ['/visibility', 'AI Visibility'],
    ['/ai-referrals', 'AI Referrals'],
    ['/traffic', 'Traffic'],
    ['/prompts', 'Prompts'],
    ['/opportunities', 'Opportunities'],
    ['/site', 'Website'],
    // The canonical Website route owns crawl detail beneath `/site`.
    ['/demand', 'Search Demand'],
  ])('resolves %s to the page title %s', (route, title) => {
    expect(renderTitle(route)).toBe(title);
  });

  it.each([
    ['/traffic/anything', 'Traffic'],
    ['/runs/abc', 'Run detail'],
    ['/runs/abc/executions/def', 'Execution evidence'],
    ['/products/abc', 'Commerce Suite'],
    ['/site/crawls/abc/pages/def', 'Page detail'],
  ])('resolves deeper route %s by longest-prefix match to %s', (route, title) => {
    expect(renderTitle(route)).toBe(title);
  });

  it('falls back to the product name for unknown routes', () => {
    expect(renderTitle('/nope')).toBe('CiteLadder');
  });

  it('renders the summary and actions slots alongside the title', () => {
    pathname.value = '/visibility';
    render(
      <PageHeader
        summary={<span>mentioned in 62% of answers</span>}
        actions={<span>Metrics</span>}
      />,
    );
    expect(screen.getByText('mentioned in 62% of answers')).toBeInTheDocument();
    expect(screen.getByText('Metrics')).toBeInTheDocument();
  });

  it('accepts an explicit title override', () => {
    pathname.value = '/visibility';
    render(<PageHeader title="Custom" />);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Custom');
  });

  it('keeps the route title visible by default', () => {
    pathname.value = '/site';
    render(<PageHeader />);
    expect(screen.getByRole('heading', { level: 1 })).not.toHaveClass('sr-only');
  });

  it('can retain an accessible-only title for an entity-owned screen', () => {
    pathname.value = '/site';
    render(<PageHeader showTitle={false} />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveClass('sr-only');
  });

  it('keeps the page-detail route title accessible-only by default', () => {
    pathname.value = '/site/crawls/crawl-id/pages/page-id';
    render(<PageHeader />);
    expect(screen.getByRole('heading', { level: 1, name: 'Page detail' })).toHaveClass('sr-only');
  });
});
