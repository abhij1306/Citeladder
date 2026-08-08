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
/**
 * One entry per `PageAnalysisStatus`. Keyed by the closed enum rather than
 * `string`, so a new backend status is a compile error instead of a row that
 * silently renders "Unknown" — the exact collapse `StateLabel` exists to
 * prevent. (`cancelled` was missed while these were `Record<string, …>`.)
 */
const STATUS_PRESENTATION: Record<
  PageSummary['analysis_status'],
  { state: DerivedState; disposition: string; reason: string }
> = {
  not_selected: {
    state: 'excluded',
    disposition: 'Inventory only',
    reason: 'Inventory only — not in the analyzed set.',
  },
  pending: { state: 'unknown', disposition: 'Queued', reason: 'Queued for analysis.' },
  running: { state: 'unknown', disposition: 'Analyzing', reason: 'Analysis in progress.' },
  completed: { state: 'observed_zero', disposition: 'Analyzed', reason: 'Analyzed.' },
  partially_completed: {
    state: 'conflicting',
    disposition: 'Partial',
    reason: 'Some dimensions could not be analyzed.',
  },
  failed: {
    state: 'failed',
    disposition: 'Failed',
    reason: 'Analysis ran and did not complete.',
  },
  error: {
    state: 'failed',
    disposition: 'Failed',
    reason: 'Analysis ran and did not complete.',
  },
  blocked: {
    state: 'unavailable',
    disposition: 'Blocked',
    reason: 'Blocked by a robots or SSRF policy.',
  },
  cancelled: {
    state: 'excluded',
    disposition: 'Cancelled',
    reason: 'The analysis was cancelled before it ran.',
  },
};

/**
 * One page of rows. The corpus is a coverage surface (§6), so a silently
 * truncated list is the exact failure it exists to prevent — a blocked or
 * failed document past the cut would simply not exist as far as the user can
 * tell. Until this pages through `next_cursor`, the truncation is stated in
 * the UI rather than hidden.
 */
const PAGE_SIZE = 50;

export function CorpusPanel({ crawlId }: Readonly<{ crawlId: string }>) {
  const query = useQuery({ ...siteHealthQueries.pages(crawlId, { limit: PAGE_SIZE }) });

  if (query.isLoading) return <p className="text-muted text-sm">Loading corpus…</p>;
  if (query.isError || !query.data) {
    return <p className="text-muted text-sm">The corpus could not be loaded.</p>;
  }

  const rows = query.data.items;
  if (rows.length === 0) {
    return <p className="text-muted text-sm">No documents have been discovered yet.</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      {query.data.next_cursor ? (
        <p className="text-muted text-xs">
          Showing the first {rows.length} documents. More were discovered — this surface does not
          page through them yet, so documents past this point are not listed here.
        </p>
      ) : null}
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
            {rows.map((row) => {
              const { state, disposition, reason } = STATUS_PRESENTATION[row.analysis_status];
              return (
                <tr key={row.site_url_id} className="border-border-subtle border-b last:border-0">
                  <td
                    className="text-foreground max-w-0 truncate px-4 py-2"
                    title={row.display_url}
                  >
                    {row.display_url}
                  </td>
                  <td className="text-muted px-4 py-2 whitespace-nowrap">{disposition}</td>
                  <td className="px-4 py-2">
                    <StateLabel state={state} />
                  </td>
                  <td className="text-muted px-4 py-2 text-xs">{reason}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
