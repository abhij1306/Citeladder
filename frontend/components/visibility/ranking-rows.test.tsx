import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { RankingRow } from '@/lib/api/types';
import { PLACEHOLDER } from '@/lib/visibility/dashboard';

import { RankingRowsTable } from './ranking-rows';

/**
 * The brand-vs-competitor rankings table is the surface where Track's measured
 * outcome is read, so its job is to distinguish four things a careless table
 * would collapse: a rate that is zero, a rate that is unknown, a metric that is
 * not yet computed, and a trend there is not enough data to draw.
 *
 * The last one matters most. A brand with one reading has no trend; drawing a
 * flat sparkline for it would invent a claim of stability the run cannot
 * support.
 */
function row(overrides: Partial<RankingRow> = {}): RankingRow {
  return {
    name: 'Acme',
    is_brand: false,
    logo_url: null,
    website_url: null,
    mention_rate: 0.5,
    citation_rate: 0.25,
    share_of_voice: 0.4,
    mention_count: 5,
    sentiment: null,
    avg_position: null,
    ...overrides,
  } as RankingRow;
}

const headers = () => screen.getAllByRole('columnheader').map((cell) => cell.textContent);

describe('RankingRowsTable', () => {
  it('ranks rows in the order supplied', () => {
    render(
      <RankingRowsTable
        rows={[row({ name: 'Acme' }), row({ name: 'Globex' }), row({ name: 'Initech' })]}
      />,
    );

    const bodyRows = screen.getAllByRole('row').slice(1);
    expect(within(bodyRows[0]!).getByText('1')).toBeVisible();
    expect(within(bodyRows[0]!).getByText('Acme')).toBeVisible();
    expect(within(bodyRows[2]!).getByText('3')).toBeVisible();
    expect(within(bodyRows[2]!).getByText('Initech')).toBeVisible();
  });

  it('marks the user’s own brand and only that row', () => {
    render(
      <RankingRowsTable rows={[row({ name: 'Acme', is_brand: true }), row({ name: 'Globex' })]} />,
    );

    expect(screen.getAllByText('You')).toHaveLength(1);
    const acmeRow = screen.getByText('Acme').closest('tr');
    expect(within(acmeRow!).getByText('You')).toBeVisible();
  });

  it('renders a zero rate as zero, not as unknown', () => {
    render(<RankingRowsTable rows={[row({ mention_rate: 0, share_of_voice: 0 })]} />);

    // "Never mentioned" is a real measurement and must not read as "we do not
    // know" — they lead to opposite decisions.
    expect(screen.queryAllByText(PLACEHOLDER)).toHaveLength(2); // sentiment + position only
    expect(screen.getAllByText('0%').length).toBeGreaterThan(0);
  });

  it('renders an unknown rate as the placeholder', () => {
    render(<RankingRowsTable rows={[row({ mention_rate: null, share_of_voice: null })]} />);

    // Sentiment and position are always placeholders, plus these two.
    expect(screen.getAllByText(PLACEHOLDER)).toHaveLength(4);
  });

  it('always places sentiment and position as not-yet-computed', () => {
    render(<RankingRowsTable rows={[row({ sentiment: 'positive', avg_position: 2 })]} />);

    // Decision B-2: these columns are declared but not computed, so the table
    // must not present stale backend values as live metrics.
    const bodyRow = screen.getAllByRole('row')[1]!;
    const cells = within(bodyRow).getAllByRole('cell');
    expect(cells.at(-1)).toHaveTextContent(PLACEHOLDER);
    expect(cells.at(-2)).toHaveTextContent(PLACEHOLDER);
  });

  it('hides the trend column when no history is supplied at all', () => {
    render(<RankingRowsTable rows={[row()]} />);

    expect(headers()).not.toContain('Trend');
  });

  it('hides the trend column when every brand has only one reading', () => {
    // One point is not a trend. An empty column would be dead chrome.
    render(
      <RankingRowsTable rows={[row({ name: 'Acme' })]} history={new Map([['Acme', [0.4]]])} />,
    );

    expect(headers()).not.toContain('Trend');
  });

  it('shows the trend column once any brand has two readings', () => {
    render(
      <RankingRowsTable rows={[row({ name: 'Acme' })]} history={new Map([['Acme', [0.4, 0.6]]])} />,
    );

    expect(headers()).toContain('Trend');
    expect(screen.getByLabelText('Acme visibility trend')).toBeInTheDocument();
  });

  it('leaves a thin brand’s trend cell empty rather than drawing a flat line', () => {
    render(
      <RankingRowsTable
        rows={[row({ name: 'Acme' }), row({ name: 'Globex' })]}
        history={
          new Map([
            ['Acme', [0.4, 0.6]],
            ['Globex', [0.5]],
          ])
        }
      />,
    );

    // A single-point sparkline would assert "flat", which is a claim about a
    // history that does not exist.
    expect(screen.getByLabelText('Acme visibility trend')).toBeInTheDocument();
    expect(screen.queryByLabelText('Globex visibility trend')).not.toBeInTheDocument();
  });

  it('renders an empty table body when there are no rows', () => {
    render(<RankingRowsTable rows={[]} />);

    expect(screen.getAllByRole('row')).toHaveLength(1); // header only
  });

  it('keeps a brand and a competitor of the same name as distinct rows', () => {
    // The React key combines the name with brand/competitor for exactly this
    // case; a name-only key would drop one of them.
    render(
      <RankingRowsTable
        rows={[row({ name: 'Acme', is_brand: true }), row({ name: 'Acme', is_brand: false })]}
      />,
    );

    expect(screen.getAllByText('Acme')).toHaveLength(2);
  });
});
