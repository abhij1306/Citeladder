'use client';

import { Card, CardContent } from '@/components/ui/card';
import { ScoreRing } from '@/components/ui/score-ring';
import { UnavailableValue } from '@/components/ui/unavailable-value';
import type { SiteCrawl, SiteHealthDashboard } from '@/lib/api/types';
import { formatScore } from '@/lib/site-health/status';

/**
 * Always-mounted score section of the canonical Site Health screen.
 *
 * The three score cards (Web Fundamentals / AEO / coverage) render in every phase:
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
  const technical = scoredValue(summary?.web_fundamentals_score);
  const aeo = scoredValue(summary?.aeo_readiness_score);
  const coverageValue =
    summary?.aeo_measurement_coverage === null || summary?.aeo_measurement_coverage === undefined
      ? null
      : summary.aeo_measurement_coverage * 100;
  const coverage = coverageValue;

  return (
    <div className="grid gap-4 sm:grid-cols-3" data-testid="score-section">
      <ScoreCard
        label="Web Fundamentals"
        value={technical}
        state={summary?.web_fundamentals_state}
        sub={measurementSub(summary?.web_fundamentals_state, summary?.web_fundamentals_coverage)}
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
        state={summary?.aeo_measurement_state}
        sub="Determinate evidence across applicable pillars"
      />
    </div>
  );
}

function scoredValue(value: number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  return value;
}

function measurementSub(state: string | undefined, coverage: number | null | undefined): string {
  const measured =
    coverage === null || coverage === undefined ? null : `${Math.round(coverage * 100)}% measured`;
  if (state === 'limited_evidence')
    return measured ? `${measured} · Limited confidence` : 'Limited confidence';
  if (state === 'not_measured' || !state) return 'Not measured';
  if (state === 'excluded') return 'Excluded from this audit';
  return measured ?? 'Measured';
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
          <p className="text-muted text-2xs font-semibold tracking-[0.06em] uppercase">{label}</p>
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
            <p className="text-muted text-2xs font-semibold tracking-[0.06em] uppercase">{label}</p>
            <span className="font-display text-foreground text-2xl font-semibold tracking-[-0.02em] tabular-nums">
              {formatScore(value)} / 100
            </span>
            <span className="text-muted text-xs leading-relaxed">{sub}</span>
          </div>
        </CardContent>
      )}
    </Card>
  );
}
