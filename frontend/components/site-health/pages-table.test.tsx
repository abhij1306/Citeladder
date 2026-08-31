import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';

import { PagesTable } from './pages-table';
import type { PageSummary } from '@/lib/api/types';

// Stub next/navigation (unavailable in jsdom). `push` is asserted by the
// clickable-row test; vi.hoisted so the hoisted mock factory can reference it.
const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}));

const UUID = '11111111-1111-4111-8111-111111111111';
const CRAWL = '22222222-2222-4222-8222-222222222222';
const SOURCE_CRAWL = '33333333-3333-4333-8333-333333333333';

function page(overrides: Partial<PageSummary> = {}): PageSummary {
  return {
    site_url_id: UUID,
    crawl_id: CRAWL,
    normalized_url: 'https://acme.com/',
    display_url: 'https://acme.com/',
    title: 'Homepage',
    monitored: true,
    analysis_status: 'completed',
    error_code: '',
    issue_count: 3,
    web_fundamentals_score: 46,
    web_fundamentals_coverage: 1,
    web_fundamentals_state: 'measured',
    aeo_readiness_score: 64,
    aeo_measurement_coverage: 0.8,
    aeo_measurement_state: 'measured',
    aeo_measurement_reason: '',
    main_content_indexable: true,
    last_audited: '2026-07-16T00:00:00Z',
    // Distinct from `title` so badge-text assertions stay unambiguous.
    page_kind: 'article',
    inbound_count: 12,
    main_content_inbound_count: 4,
    depth_from_home: 1,
    ...overrides,
  };
}

describe('PagesTable', () => {
  it('renders scores for a completed page', () => {
    render(<PagesTable pages={[page()]} crawlId={CRAWL} />);
    expect(screen.getByText('Homepage')).toBeInTheDocument();
    expect(screen.getByText('46')).toBeInTheDocument();
    expect(screen.getByText('64')).toBeInTheDocument();
  });

  it('shows a non-null limited-evidence score without an internal confidence subtitle', () => {
    render(
      <PagesTable
        crawlId={CRAWL}
        pages={[
          page({
            web_fundamentals_state: 'limited_evidence',
            web_fundamentals_score: 46,
            aeo_measurement_state: 'excluded',
            aeo_readiness_score: null,
            aeo_measurement_coverage: null,
          }),
        ]}
      />,
    );
    expect(screen.getAllByText('Excluded')).toHaveLength(2);
    const row = screen.getByText('Homepage').closest('tr');
    expect(row).not.toBeNull();
    expect(within(row!).getByText('46')).toBeInTheDocument();
    expect(within(row!).queryByText(/confidence/i)).not.toBeInTheDocument();
    expect(within(row!).queryByText(/100% measured/i)).not.toBeInTheDocument();
  });

  it('renders the page-kind badge for a classified page', () => {
    render(<PagesTable pages={[page()]} crawlId={CRAWL} />);
    expect(screen.getByText('Article')).toBeInTheDocument();
  });

  it('renders the not-measured state for an unclassified page (null page_kind)', () => {
    render(<PagesTable pages={[page({ page_kind: null })]} crawlId={CRAWL} />);
    expect(screen.queryByText('Article')).not.toBeInTheDocument();
    expect(screen.getAllByText('Not measured').length).toBeGreaterThan(0);
  });

  it('uses the persisted unresolved-purpose reason for Other pages', () => {
    render(
      <PagesTable
        crawlId={CRAWL}
        pages={[
          page({
            page_kind: 'other',
            aeo_readiness_score: null,
            aeo_measurement_coverage: null,
            aeo_measurement_state: 'not_measured',
            aeo_measurement_reason: 'page_purpose_unresolved',
          }),
        ]}
      />,
    );

    expect(screen.getByText('Other')).toBeInTheDocument();
    expect(screen.getAllByText('Not measured').length).toBeGreaterThan(0);
    expect(screen.queryByText(/purpose unresolved/i)).not.toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('renders the not-measured state for a blocked page — never a fabricated zero', () => {
    render(
      <PagesTable
        crawlId={CRAWL}
        pages={[
          page({
            site_url_id: '33333333-3333-4333-8333-333333333333',
            title: 'Admin Panel',
            analysis_status: 'blocked',
            issue_count: null,
            web_fundamentals_score: null,
            web_fundamentals_coverage: null,
            web_fundamentals_state: 'not_measured',
            aeo_readiness_score: null,
            aeo_measurement_coverage: null,
            aeo_measurement_state: 'not_measured',
            main_content_indexable: null,
            last_audited: null,
            page_kind: null,
          }),
        ]}
      />,
    );
    // No zeroes rendered for the missing scores.
    expect(screen.queryByText('0')).not.toBeInTheDocument();
    // Blocked status badge is shown.
    expect(screen.getByText('Blocked')).toBeInTheDocument();
    // Placeholder appears for the missing score/issue cells.
    expect(screen.getAllByText('Not measured').length).toBeGreaterThan(0);
  });

  it('links View to the per-URL detail route', () => {
    render(<PagesTable pages={[page()]} crawlId={CRAWL} />);
    const view = screen.getByText('View');
    const anchor = view.closest('a');
    expect(anchor).not.toBeNull();
    expect(anchor).toHaveAttribute('href', `/site/crawls/${CRAWL}/pages/${UUID}`);
  });

  it('navigates to the per-URL detail when the row is clicked', () => {
    push.mockClear();
    render(<PagesTable pages={[page()]} crawlId={CRAWL} />);
    fireEvent.click(screen.getByText('Homepage'));
    expect(push).toHaveBeenCalledWith(`/site/crawls/${CRAWL}/pages/${UUID}`);
  });

  it('links an inherited discovered row to the crawl that owns its detail', () => {
    render(
      <PagesTable
        pages={[page({ crawl_id: SOURCE_CRAWL, analysis_status: 'not_selected' })]}
        crawlId={CRAWL}
      />,
    );
    expect(screen.getByText('View').closest('a')).toHaveAttribute(
      'href',
      `/site/crawls/${SOURCE_CRAWL}/pages/${UUID}`,
    );
  });

  it('renders the final PR2 page metrics', () => {
    render(<PagesTable pages={[page()]} crawlId={CRAWL} />);
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'AEO Coverage' })).toBeInTheDocument();
    expect(
      screen.getByRole('columnheader', { name: 'Main-content indexable' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Indexable')).toBeInTheDocument();
  });

  it('shows an unmeasured link metric as Not measured, never a zero', () => {
    render(
      <PagesTable
        pages={[page({ inbound_count: null, main_content_indexable: null })]}
        crawlId={CRAWL}
      />,
    );
    expect(screen.getAllByText('Not measured').length).toBeGreaterThanOrEqual(2);
  });

  it('asks the server to reorder, and marks the active column', async () => {
    const onSortChange = vi.fn();
    const { rerender } = render(
      <PagesTable pages={[page()]} crawlId={CRAWL} sort="url" onSortChange={onSortChange} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^Inbound/ }));
    expect(onSortChange).toHaveBeenCalledWith('inbound');

    rerender(
      <PagesTable pages={[page()]} crawlId={CRAWL} sort="inbound" onSortChange={onSortChange} />,
    );
    expect(screen.getByRole('columnheader', { name: /^Inbound/ })).toHaveAttribute(
      'aria-sort',
      'descending',
    );
  });

  it('clicking the active sort returns to the default URL order', () => {
    const onSortChange = vi.fn();
    render(
      <PagesTable pages={[page()]} crawlId={CRAWL} sort="inbound" onSortChange={onSortChange} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^Inbound/ }));
    expect(onSortChange).toHaveBeenCalledWith('url');
  });

  it('renders plain link headers where the table cannot reorder', () => {
    render(<PagesTable pages={[page()]} crawlId={CRAWL} />);
    expect(screen.queryByRole('button', { name: /^Inbound/ })).not.toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Inbound' })).toBeInTheDocument();
  });
});
