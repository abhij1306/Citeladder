'use client';

import { Card, CardContent } from '@/components/ui/card';
import { ScoreRing } from '@/components/ui/score-ring';
import { UnavailableValue } from '@/components/ui/unavailable-value';
import type { SiteCrawl, SiteHealthDashboard } from '@/lib/api/types';
import { formatScore } from '@/lib/site-health/status';

/**
 * Always-mounted score section of the canonical Site Health screen.
 *
 * The three score cards (Site Health / Web Fundamentals / AEO) render in every phase:
 * placeholders before any analysis has produced data, a live running mean
 * while analysis is in flight, and the final `score_summary` once it lands.
 * Scores appear IN PLACE — the section never unmounts, so finishing a crawl
 * updates the cards instead of jumping to a different screen. Missing scores
 * render `Not measured`, never a fabricated zero.
 */
export function ScoreSection({
  crawl,
  dashboard,
}: Readonly<{
  crawl: SiteCrawl | null;
  dashboard: SiteHealthDashboard | undefined;
}>) {
  const summary = dashboard?.score_summary ?? crawl?.score_summary ?? null;
  const technical =
    summary?.technical_integrity_state === 'measured' ? summary.technical_integrity_score : null;
  const aeo = summary?.aeo_measurement_state === 'measured' ? summary.aeo_readiness_score : null;
  const coverage =
    summary?.aeo_measurement_coverage === null || summary?.aeo_measurement_coverage === undefined
      ? null
      : summary.aeo_measurement_coverage * 100;

  return (
    <div className="grid gap-4 sm:grid-cols-3" data-testid="score-section">
      <ScoreCard
        label="Technical Integrity"
        value={technical}
        state={summary?.technical_integrity_state}
        sub={measurementSub(
          summary?.technical_integrity_state,
          summary?.technical_integrity_coverage,
        )}
      />
      <ScoreCard
        label="AEO Readiness"
        value={aeo}
        state={summary?.aeo_measurement_state}
        sub={measurementSub(summary?.aeo_measurement_state, summary?.aeo_measurement_coverage)}
      />
      <ScoreCard
        label="AEO Measurement Coverage"
        value={coverage}
        state={coverage === null ? 'not_measured' : 'measured'}
        sub="Determinate evidence across applicable pillars"
      />
    </div>
  );
}

function measurementSub(state: string | undefined, coverage: number | null | undefined): string {
  if (state === 'limited_evidence') return 'Limited evidence';
  if (state === 'not_measured' || !state) return 'Not measured';
  if (state === 'excluded') return 'Excluded from this audit';
  return coverage === null || coverage === undefined
    ? 'Measured'
    : `${Math.round(coverage * 100)}% evidence coverage`;
}

function ScoreCard({
  label,
  value,
  state,
  sub,
}: Readonly<{ label: string; value: number | null; state: string | undefined; sub: string }>) {
  return (
    <Card className="border-border/70">
      {value === null ? (
        <CardContent className="grid h-full content-center gap-1 p-[var(--card-padding)] sm:p-[var(--card-padding)]">
          <p className="text-muted text-xs font-semibold">{label}</p>
          {state === 'limited_evidence' || state === 'excluded' ? (
            <span className="value-placeholder font-sans text-sm font-medium">
              {state === 'limited_evidence' ? 'Limited evidence' : 'Excluded'}
            </span>
          ) : (
            <UnavailableValue state="not_measured" className="text-sm" />
          )}
          <span className="text-muted text-xs leading-relaxed">{sub}</span>
        </CardContent>
      ) : (
        <CardContent className="flex h-full items-center gap-4 p-[var(--card-padding)] sm:p-[var(--card-padding)]">
          <ScoreRing value={value} size={72} label={`${label} score: ${Math.round(value)}`} />
          <div className="grid gap-1">
            <p className="text-muted text-xs font-semibold">{label}</p>
            <span className="font-display text-foreground text-xl font-semibold tabular-nums">
              {formatScore(value)} / 100
            </span>
            <span className="text-muted text-xs leading-relaxed">{sub}</span>
          </div>
        </CardContent>
      )}
    </Card>
  );
}
