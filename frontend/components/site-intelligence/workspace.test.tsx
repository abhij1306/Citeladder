import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SiteIntelligenceWorkspace } from './workspace';
import type { IntelligenceOverview } from '@/lib/api/types';

const replace = vi.fn();
let searchParams = new URLSearchParams();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace }),
  usePathname: () => '/site-health',
  useSearchParams: () => searchParams,
}));

const getOverview = vi.fn();
const getEntities = vi.fn();
const getAssertions = vi.fn();
const getContradictions = vi.fn();
const getRelations = vi.fn();
const getSchemaGraph = vi.fn();

vi.mock('@/lib/api/site-intelligence', async () => {
  const { queryOptions } = await import('@tanstack/react-query');
  return {
    siteIntelligenceQueries: {
      overview: (p: string, c?: string) =>
        queryOptions({ queryKey: ['o', p, c], queryFn: () => getOverview() }),
      entities: (p: string, c?: string) =>
        queryOptions({ queryKey: ['e', p, c], queryFn: () => getEntities() }),
      assertions: (p: string, c?: string) =>
        queryOptions({ queryKey: ['a', p, c], queryFn: () => getAssertions() }),
      contradictions: (p: string, c?: string) =>
        queryOptions({ queryKey: ['c', p, c], queryFn: () => getContradictions() }),
      relations: (p: string, c?: string) =>
        queryOptions({ queryKey: ['r', p, c], queryFn: () => getRelations() }),
      schemaGraph: (p: string, c?: string) =>
        queryOptions({ queryKey: ['s', p, c], queryFn: () => getSchemaGraph() }),
    },
  };
});

function overview(patch: Partial<IntelligenceOverview> = {}): IntelligenceOverview {
  return {
    available: true,
    reason: null,
    packed: true,
    manifest: { pack_id: 'education', pack_version: '1.0.0' },
    crawl: { id: 'crawl-1', status: 'completed', root_url: 'https://a.test/', created_at: null },
    snapshot_id: 'snap-1',
    corpus: {
      by_disposition: { analyze: 10 },
      by_item_kind: { html_page: 10 },
      discovered: 10,
      analyzable: 10,
      inventory_only: 0,
      documents: 0,
    },
    knowledge: {
      entity_count: 1,
      assertion_count: 11,
      relation_count: 0,
      contradiction_count: 0,
      pages_considered: 10,
      pages_contributing: 10,
      entity_type_ids: ['education.organization'],
      warnings: [],
    },
    coverage: {
      answered_ratio: 0.1,
      denominator: 29,
      counts: { missing: 16 },
      questions: [
        {
          question_id: 'education.fees',
          label: 'Fees',
          state: 'unavailable_evidence',
          journey_stage_id: 'education.evaluate',
          reason: 'no page that could answer this was successfully acquired',
          satisfied_predicate_ids: [],
          missing_predicate_ids: [],
          answering_role_ids: [],
        },
      ],
    },
    journeys: [],
    dimensions: {
      composite_score: 0.6,
      composite_coverage: 0.93,
      dimensions: [
        {
          dimension_id: 'machine_clarity',
          label: 'Machine clarity',
          score: 0.5,
          coverage: 0.75,
          components: [
            { component_id: 'schema_presence', label: 'Structured data present', score: 0 },
            { component_id: 'entity_consistency', label: 'Entity naming', score: null },
          ],
        },
      ],
    },
    versions: { dimension_formula: 'si-dimensions-1' },
    ...patch,
  };
}

function renderWorkspace(data: IntelligenceOverview = overview()) {
  getOverview.mockResolvedValue(data);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SiteIntelligenceWorkspace
        projectId="project-1"
        crawlId="crawl-1"
        pagesPanel={<div>pages panel content</div>}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  searchParams = new URLSearchParams();
  getEntities.mockResolvedValue({ crawl_id: 'crawl-1', total: 0, items: [] });
  getAssertions.mockResolvedValue({ crawl_id: 'crawl-1', total: 0, items: [] });
  getContradictions.mockResolvedValue({ crawl_id: 'crawl-1', total: 0, items: [] });
  getRelations.mockResolvedValue({ crawl_id: 'crawl-1', total: 0, items: [] });
  getSchemaGraph.mockResolvedValue({
    crawl_id: 'crawl-1',
    analyzed_pages: 10,
    pages_with_schema: 0,
    types: [],
    invalid: [],
  });
});

describe('SiteIntelligenceWorkspace', () => {
  it('renders all six panel tabs and defaults to Pages', async () => {
    renderWorkspace();
    for (const label of ['Overview', 'Pages', 'Knowledge', 'Schema', 'Journeys', 'Evidence']) {
      expect(screen.getByRole('tab', { name: label })).toBeInTheDocument();
    }
    // Pages is the crawl lifecycle a user arrives mid-way through; Overview
    // says nothing until a snapshot exists.
    expect(screen.getByRole('tab', { name: 'Pages' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('pages panel content')).toBeInTheDocument();
  });

  it('mirrors the selected panel to the URL', async () => {
    renderWorkspace();
    await userEvent.click(screen.getByRole('tab', { name: 'Knowledge' }));
    expect(replace).toHaveBeenCalledWith('/site-health?panel=knowledge', { scroll: false });
  });

  it('renders the panel named by the URL, not the default', async () => {
    searchParams = new URLSearchParams('panel=schema');
    renderWorkspace();
    await waitFor(() => expect(screen.getByText('Structured data')).toBeInTheDocument());
  });

  it('falls back to the default panel for an unknown value, never nothing', async () => {
    searchParams = new URLSearchParams('panel=nonsense');
    renderWorkspace();
    expect(screen.getByRole('tab', { name: 'Pages' })).toHaveAttribute('aria-selected', 'true');
  });

  it('renders only one panel at a time', async () => {
    searchParams = new URLSearchParams('panel=overview');
    renderWorkspace();
    await waitFor(() => expect(screen.getByText('Site Intelligence')).toBeInTheDocument());
    expect(screen.queryByText('pages panel content')).not.toBeInTheDocument();
  });

  it('shows an unmeasurable component as such, never as zero', async () => {
    searchParams = new URLSearchParams('panel=overview');
    renderWorkspace();
    await waitFor(() =>
      expect(screen.getByText(/Not measurable: Entity naming/)).toBeInTheDocument(),
    );
  });

  it('distinguishes "no snapshot yet" from "no industry pack"', async () => {
    searchParams = new URLSearchParams('panel=overview');
    const { unmount } = renderWorkspace(
      overview({ available: false, reason: 'this crawl has not finished' }),
    );
    await waitFor(() =>
      expect(screen.getByText(/this crawl has not finished/)).toBeInTheDocument(),
    );
    unmount();

    renderWorkspace(overview({ packed: false }));
    await waitFor(() =>
      expect(screen.getByText(/No industry pack applied to this crawl/)).toBeInTheDocument(),
    );
  });

  it('labels unavailable evidence as evidence, not as a site failure', async () => {
    searchParams = new URLSearchParams('panel=evidence');
    renderWorkspace();
    await waitFor(() =>
      expect(screen.getByText('Evidence unavailable')).toBeInTheDocument(),
    );
  });
});
