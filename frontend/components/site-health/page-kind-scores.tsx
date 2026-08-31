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
import { UnavailableValue } from '@/components/ui/unavailable-value';
import { PageKindBadge } from '@/components/site-health/page-kind-badge';
import type { SiteCrawl, SiteHealthDashboard } from '@/lib/api/types';
import { byPageKindRows } from '@/lib/site-health/page-kinds';
import { formatScore } from '@/lib/site-health/status';
import { cn } from '@/lib/utils';

/**
 * Dashboard per-page-kind score breakdown.
 * Renders `score_summary.by_page_kind` — one row per observed page-kind
 * bucket with its analyzed count and mean Web Fundamentals and AEO scores.
 * The panel is data-driven and follows the same dashboard-then-crawl fallback
 * as the score cards. Classification completeness and the exact scored cohort
 * come from their own persisted fields; an `other` bucket remains visible but
 * never enters the AEO scored composition.
 * Missing means render `Not measured`, never a fabricated zero.
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

  return (
    <Card data-testid="page-kind-scores">
      <CardContent className="grid gap-3">
        <div className="grid gap-0.5">
          <Label>Scores by Page Kind</Label>
          <span className="text-secondary text-sm">
            Mean scores across the analyzed pages of each type.
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
                <TableHead numeric>AEO Readiness</TableHead>
                <TableHead numeric>AEO Coverage</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.page_kind}>
                  <TableCell>
                    <PageKindBadge pageKind={row.page_kind} className="text-xs" />
                  </TableCell>
                  <TableCell numeric className="mono text-secondary">
                    {row.analyzed_count}
                  </TableCell>
                  <TableCell
                    numeric
                    className={cn('mono font-medium', scoreTextClass(row.web_fundamentals_score))}
                  >
                    <MeasurementValue
                      score={row.web_fundamentals_score}
                      coverage={row.web_fundamentals_coverage}
                      state={row.web_fundamentals_state}
                    />
                  </TableCell>
                  <TableCell
                    numeric
                    className={cn('mono font-medium', scoreTextClass(row.aeo_readiness_score))}
                  >
                    <MeasurementValue
                      score={row.aeo_readiness_score}
                      coverage={row.aeo_measurement_coverage}
                      state={row.aeo_measurement_state}
                    />
                  </TableCell>
                  <TableCell numeric className="mono font-medium">
                    {row.aeo_measurement_coverage === null ? (
                      <UnavailableValue state="not_measured" />
                    ) : (
                      `${Math.round(row.aeo_measurement_coverage * 100)}%`
                    )}
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

function MeasurementValue({
  score,
  coverage,
  state,
}: Readonly<{ score: number | null; coverage: number | null; state: string }>) {
  if (score !== null) {
    const coverageLabel =
      coverage === null ? 'Coverage unavailable' : `${Math.round(coverage * 100)}% measured`;
    return (
      <span className="grid gap-0.5">
        <span>{formatScore(score)}</span>
        <span className="text-muted text-xs font-normal normal-case">
          {coverageLabel} · {measurementConfidence(state)}
        </span>
      </span>
    );
  }
  if (state === 'limited_evidence') return 'Limited evidence';
  if (state === 'excluded') return 'Excluded';
  return <UnavailableValue state="not_measured" />;
}

function measurementConfidence(state: string): string {
  if (state === 'measured') return 'High confidence';
  if (state === 'limited_evidence') return 'Moderate confidence';
  if (state === 'excluded') return 'Excluded';
  return 'Not measured';
}
