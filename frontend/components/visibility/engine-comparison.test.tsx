import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { RankingRow, Visibility, VisibilityEngine } from '@/lib/api/types';
import { PLACEHOLDER } from '@/lib/visibility/dashboard';

import { EngineComparison } from './engine-comparison';

/**
 * Per-model comparison plus the share-of-answers bars.
 *
 * The subtle rule is in the accessible summary: it is derived from the SAME
 * source as the bars and numerals (`share_of_voice`), so a row with no share
 * data is omitted from the announcement rather than announced with a
 * mention-derived share that its zero-width bar does not show. A screen-reader
 * user and a sighted user must be told the same thing.
 */
function engine(overrides: Partial<VisibilityEngine> = {}): VisibilityEngine {
  return {
    logical_engine: 'gemini',
    total_completed: 12,
    brand_mention_rate: 0.5,
    owned_citation_rate: 0.25,
    search_use_rate: 1,
    visibility_score: 62,
    ...overrides,
  } as VisibilityEngine;
}

function ranking(overrides: Partial<RankingRow> = {}): RankingRow {
  return {
    name: 'Acme',
    is_brand: false,
    logo_url: null,
    website_url: null,
    mention_rate: 0.5,
    citation_rate: 0.2,
    share_of_voice: 0.4,
    mention_count: 3,
    sentiment: null,
    avg_position: null,
    ...overrides,
  } as RankingRow;
}

function visibility(per_engine: VisibilityEngine[], rankings: RankingRow[] = []): Visibility {
  return { per_engine, rankings } as Visibility;
}

const shareFigure = () => screen.queryByRole('img', { name: /^Share of voice:/ });

describe('EngineComparison — by model', () => {
  it('renders one row per engine with its measured columns', () => {
    render(
      <EngineComparison
        visibility={visibility([engine({ logical_engine: 'gemini', total_completed: 12 })])}
        filter="all"
      />,
    );

    const row = screen.getAllByRole('row')[1]!;
    expect(within(row).getByText('Gemini')).toBeVisible();
    expect(within(row).getByText('62%')).toBeVisible();
    expect(within(row).getByText('12')).toBeVisible();
  });

  it('orders engines by the catalog display order, not the response order', () => {
    render(
      <EngineComparison
        visibility={visibility([
          engine({ logical_engine: 'claude' }),
          engine({ logical_engine: 'gemini' }),
          engine({ logical_engine: 'chatgpt' }),
        ])}
        filter="all"
      />,
    );

    const names = screen
      .getAllByRole('row')
      .slice(1)
      .map((row) => within(row).getAllByRole('cell')[0]!.textContent);
    expect(names).toEqual(['ChatGPT', 'Gemini', 'Claude']);
  });

  it('narrows to the selected engine', () => {
    render(
      <EngineComparison
        visibility={visibility([
          engine({ logical_engine: 'gemini' }),
          engine({ logical_engine: 'claude' }),
        ])}
        filter="gemini"
      />,
    );

    expect(screen.getAllByRole('row')).toHaveLength(2); // header + gemini
    expect(screen.getByText('Gemini')).toBeVisible();
    expect(screen.queryByText('Claude')).not.toBeInTheDocument();
  });

  it('says the filter excluded everything rather than showing a bare table', () => {
    render(
      <EngineComparison
        visibility={visibility([engine({ logical_engine: 'gemini' })])}
        filter="claude"
      />,
    );

    expect(screen.getByText('No model results match the current filter.')).toBeVisible();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('renders an unknown visibility score as the placeholder', () => {
    render(
      <EngineComparison
        visibility={visibility([engine({ visibility_score: null })])}
        filter="all"
      />,
    );

    const row = screen.getAllByRole('row')[1]!;
    expect(within(row).getAllByRole('cell')[1]).toHaveTextContent(PLACEHOLDER);
  });

  it('renders a zero score as a measurement', () => {
    render(
      <EngineComparison visibility={visibility([engine({ visibility_score: 0 })])} filter="all" />,
    );

    const row = screen.getAllByRole('row')[1]!;
    expect(within(row).getAllByRole('cell')[1]).toHaveTextContent('0%');
  });
});

describe('EngineComparison — share of answers', () => {
  it('says nothing was mentioned rather than drawing empty bars', () => {
    render(<EngineComparison visibility={visibility([engine()], [])} filter="all" />);

    expect(screen.getByText(/No mentions recorded for this run/)).toBeVisible();
    expect(shareFigure()).not.toBeInTheDocument();
  });

  it('omits a brand that was never mentioned', () => {
    render(
      <EngineComparison
        visibility={visibility(
          [engine()],
          [
            ranking({ name: 'Acme', mention_count: 2 }),
            ranking({ name: 'Ghost', mention_count: 0 }),
          ],
        )}
        filter="all"
      />,
    );

    expect(shareFigure()).toHaveAttribute('aria-label', expect.stringContaining('Acme'));
    expect(shareFigure()).not.toHaveAttribute('aria-label', expect.stringContaining('Ghost'));
  });

  it('announces the same shares the bars render', () => {
    render(
      <EngineComparison
        visibility={visibility(
          [engine()],
          [
            ranking({ name: 'Acme', is_brand: true, share_of_voice: 0.6 }),
            ranking({ name: 'Globex', share_of_voice: 0.4 }),
          ],
        )}
        filter="all"
      />,
    );

    expect(shareFigure()).toHaveAttribute('aria-label', 'Share of voice: Acme 60%, Globex 40%');
  });

  it('announces a row with no share data without inventing a percentage', () => {
    render(
      <EngineComparison
        visibility={visibility(
          [engine()],
          [
            ranking({ name: 'Acme', share_of_voice: 0.5 }),
            ranking({ name: 'Unknown', share_of_voice: null, mention_count: 2 }),
          ],
        )}
        filter="all"
      />,
    );

    expect(shareFigure()).toHaveAttribute(
      'aria-label',
      'Share of voice: Acme 50%, Unknown share unavailable',
    );
  });

  it('names every mentioned row when all share data is unavailable', () => {
    render(
      <EngineComparison
        visibility={visibility(
          [engine()],
          [ranking({ name: 'Unknown', share_of_voice: null, mention_count: 2 })],
        )}
        filter="all"
      />,
    );

    expect(shareFigure()).toHaveAttribute(
      'aria-label',
      'Share of voice: Unknown share unavailable',
    );
  });

  it('clamps an out-of-range share into the announced percentage', () => {
    render(
      <EngineComparison
        visibility={visibility([engine()], [ranking({ name: 'Acme', share_of_voice: 1.4 })])}
        filter="all"
      />,
    );

    expect(shareFigure()).toHaveAttribute('aria-label', 'Share of voice: Acme 100%');
  });
});
