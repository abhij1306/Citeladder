'use client';

import { Card, CardContent } from '@/components/ui/card';
import { scoreTextClass } from '@/components/ui/score-band';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Label } from '@/components/ui/typography';
import { PageKindBadge } from '@/components/site-health/page-kind-badge';
import type { SiteCrawl, SiteHealthDashboard } from '@/lib/api/types';
import { byPageKindRows } from '@/lib/site-health/page-kinds';
import { formatScore } from '@/lib/site-health/status';
import { cn } from '@/lib/utils';

/**
 * Dashboard per-page-kind score breakdown.
 *
 * Renders `score_summary.by_page_kind` — one row per classified page kind with
 * its analyzed count and mean Web Fundamentals / AEO / overall scores. The
 * panel is data-driven: it appears once a score summary exists (a mid-run
 * projection included) and follows the same dashboard-then-crawl fallback as
 * the score cards. An empty breakdown means analysis has not classified any
 * page yet; missing mean scores render `Not measured`, never a fabricated zero.
 *
 * READ-ONLY by design. This used to expand each row into an accordion holding
 * its own paginated URL list, checkboxes, and a "Re-analyze selected" button —
 * a page-selection UI nested inside a table cell. The canonical inventory is
 * the only URL surface; re-auditing one page belongs on its detail screen.
 */
export function PageKindScores({
  crawl,
  dashboard,
}: Readonly<{
  crawl: SiteCrawl | null;
  dashboard: SiteHealthDashboard | undefined;
}>) {
  const summary = dashboard?.score_summary ?? crawl?.score_summary ?? null;
  if (summary === null) return null;

  const rows = byPageKindRows(summary.by_page_kind);
  const unclassified = summary.by_page_kind.other?.analyzed_count ?? 0;
  const measured = rows.reduce((total, row) => total + row.analyzed_count, 0);

  return (
    <Card data-testid="page-kind-scores">
      <CardContent className="grid gap-3">
        <div className="grid gap-0.5">
          <Label>Scores by Page Kind</Label>
          <span className="text-secondary text-sm">
            {unclassified > 0
              ? `${unclassified} of ${measured} analyzed pages could not be classified; their AEO score is not measured.`
              : 'Mean scores across the analyzed pages of each type.'}
          </span>
        </div>
        {rows.length === 0 ? (
          <p className="text-secondary text-sm">
            Per-page-kind scores appear once the analysis classifies your pages.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Page Kind</TableHead>
                <TableHead numeric>Analyzed</TableHead>
                <TableHead numeric>Web Fundamentals</TableHead>
                <TableHead numeric>AEO</TableHead>
                <TableHead numeric>Overall</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.page_kind}>
                  <TableCell>
                    <PageKindBadge pageKind={row.page_kind} />
                  </TableCell>
                  <TableCell numeric className="mono text-secondary">
                    {row.analyzed_count}
                  </TableCell>
                  <TableCell
                    numeric
                    className={cn('mono font-medium', scoreTextClass(row.technical_score))}
                  >
                    {formatScore(row.technical_score)}
                  </TableCell>
                  <TableCell
                    numeric
                    className={cn('mono font-medium', scoreTextClass(row.aeo_score))}
                  >
                    {formatScore(row.aeo_score)}
                  </TableCell>
                  <TableCell
                    numeric
                    className={cn('mono font-medium', scoreTextClass(row.overall_score))}
                  >
                    {formatScore(row.overall_score)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
