'use client';

import { useQuery } from '@tanstack/react-query';

import { StateLabel, type DerivedState } from '@/components/intelligence/state-label';
import { siteHealthQueries } from '@/lib/api/site-health';
import type { PageSummary } from '@/lib/api/types';

/**
 * Corpus (§7.2) — disposition per document, with reasons.
 *
 * Backed by the `/pages` projection rather than `/inventory`: only page rows
 * carry `analysis_status`, and the disposition IS the status. Inventory rows
 * have no status field, so they cannot answer "why was this not analyzed".
 *
 * Rows are never hidden. A URL the crawler saw but did not analyze is a fact
 * about the corpus, and dropping it makes coverage look better than it is (§6).
 * Analysis status maps onto the shared `StateLabel` vocabulary so "not
 * selected", "blocked" and "failed" stay three visibly different things rather
 * than collapsing into one empty cell.
 */
const STATUS_STATE: Record<string, DerivedState> = {
  not_selected: 'excluded',
  pending: 'unknown',
  running: 'unknown',
  completed: 'observed_zero',
  partially_completed: 'conflicting',
  failed: 'failed',
  error: 'failed',
  blocked: 'unavailable',
};

const STATUS_REASON: Record<string, string> = {
  not_selected: 'Inventory only — not in the analyzed set.',
  pending: 'Queued for analysis.',
  running: 'Analysis in progress.',
  completed: 'Analyzed.',
  partially_completed: 'Some dimensions could not be analyzed.',
  failed: 'Analysis ran and did not complete.',
  error: 'Analysis ran and did not complete.',
  blocked: 'Blocked by a robots or SSRF policy.',
};

function dispositionOf(row: PageSummary): string {
  if (row.analysis_status === 'completed') return 'Analyzed';
  if (row.analysis_status === 'not_selected') return 'Inventory only';
  return 'Excluded';
}

export function CorpusPanel({ crawlId }: Readonly<{ crawlId: string }>) {
  const query = useQuery({ ...siteHealthQueries.pages(crawlId, { limit: 50 }) });

  if (query.isLoading) return <p className="text-muted text-sm">Loading corpus…</p>;
  if (query.isError || !query.data) {
    return <p className="text-muted text-sm">The corpus could not be loaded.</p>;
  }

  const rows = query.data.items;
  if (rows.length === 0) {
    return <p className="text-muted text-sm">No documents have been discovered yet.</p>;
  }

  return (
    <div className="border-border-subtle bg-panel overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="border-border-subtle bg-well border-b">
          <tr>
            <th className="text-subtle px-4 py-2 text-left text-xs font-medium">URL</th>
            <th className="text-subtle px-4 py-2 text-left text-xs font-medium">Disposition</th>
            <th className="text-subtle px-4 py-2 text-left text-xs font-medium">State</th>
            <th className="text-subtle px-4 py-2 text-left text-xs font-medium">Reason</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.site_url_id} className="border-border-subtle border-b last:border-0">
              <td className="text-foreground max-w-0 truncate px-4 py-2" title={row.display_url}>
                {row.display_url}
              </td>
              <td className="text-muted px-4 py-2 whitespace-nowrap">{dispositionOf(row)}</td>
              <td className="px-4 py-2">
                <StateLabel state={STATUS_STATE[row.analysis_status] ?? 'unknown'} />
              </td>
              <td className="text-muted px-4 py-2 text-xs">
                {STATUS_REASON[row.analysis_status] ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
