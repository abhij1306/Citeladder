import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const { queryResult } = vi.hoisted(() => ({
  queryResult: {
    data: undefined as unknown,
    isLoading: false,
    isError: false,
  },
}));

// `siteHealthQueries` builds its options with `queryOptions`, so the mock has
// to provide it as well as `useQuery`.
vi.mock('@tanstack/react-query', () => ({
  useQuery: () => queryResult,
  queryOptions: (options: unknown) => options,
}));

import { CorpusPanel } from './corpus-panel';

function row(overrides: Record<string, unknown> = {}) {
  return {
    site_url_id: 'u1',
    crawl_id: 'c1',
    normalized_url: 'https://acme.com/a',
    display_url: 'https://acme.com/a',
    title: 'A',
    monitored: true,
    analysis_status: 'completed',
    error_code: '',
    issue_count: 0,
    technical_score: null,
    aeo_score: null,
    overall_score: null,
    last_audited: null,
    page_kind: null,
    ...overrides,
  };
}

describe('CorpusPanel', () => {
  it('shows unanalyzed documents rather than hiding them', () => {
    // §6: dropping a row the crawler saw makes coverage look better than it is.
    queryResult.data = { items: [row({ analysis_status: 'not_selected' })], next_cursor: null };
    queryResult.isLoading = false;
    queryResult.isError = false;
    render(<CorpusPanel crawlId="c1" />);

    expect(screen.getByText('Inventory only')).toBeInTheDocument();
    expect(screen.getByText('Inventory only — not in the analyzed set.')).toBeInTheDocument();
  });

  it('keeps blocked, failed and cancelled visibly different', () => {
    queryResult.data = {
      items: [
        row({ site_url_id: 'u1', analysis_status: 'blocked' }),
        row({ site_url_id: 'u2', analysis_status: 'error' }),
        row({ site_url_id: 'u3', analysis_status: 'cancelled' }),
      ],
      next_cursor: null,
    };
    const { container } = render(<CorpusPanel crawlId="c1" />);

    // Read the state chips specifically: "Failed" is also a disposition, so a
    // bare text query is ambiguous.
    const states = Array.from(container.querySelectorAll('[data-state]')).map(
      (node) => node.textContent,
    );
    expect(states).toEqual(['Unavailable', 'Failed', 'Excluded']);
  });

  it('reports an empty corpus without implying zero coverage', () => {
    queryResult.data = { items: [], next_cursor: null };
    render(<CorpusPanel crawlId="c1" />);

    expect(screen.getByText('No documents have been discovered yet.')).toBeInTheDocument();
  });
});
