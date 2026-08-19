'use client';

import { Card, CardContent } from '@/components/ui/card';
import { ScoreRing } from '@/components/ui/score-ring';
import type { PageSummary, SiteCrawl, SiteHealthDashboard } from '@/lib/api/types';
import { PLACEHOLDER, formatScore } from '@/lib/site-health/status';

/**
 * Always-mounted score section of the canonical Site Health screen.
 *
 * The three score cards (Site Health / Web Fundamentals / AEO) render in every phase:
 * placeholders before any analysis has produced data, a live running mean
 * while analysis is in flight, and the final `score_summary` once it lands.
 * Scores appear IN PLACE — the section never unmounts, so finishing a crawl
 * updates the cards instead of jumping to a different screen. Missing scores
 * render `—`, never a fabricated zero.
 */
export function ScoreSection({
  crawl,
  dashboard,
  pages,
  analyzing,
  selectedTotal,
}: Readonly<{
  crawl: SiteCrawl | null;
  dashboard: SiteHealthDashboard | undefined;
  /** Bounded monitored-page window — live score preview only, never counts. */
  pages: PageSummary[];
  /** True while analysis is running (enables the live running-mean fallback). */
  analyzing: boolean;
  /** This project's active monitored count; null until loaded. */
  selectedTotal: number | null;
}>) {
  const summary = dashboard?.score_summary ?? crawl?.score_summary ?? null;
  const scores = scoreValues(summary, pages, analyzing);

  return (
    <div className="grid gap-4 sm:grid-cols-3" data-testid="score-section">
      <ScoreCard
        label="Site Health"
        value={scores.overall}
        sub={overallSub(summary, analyzing, crawl, selectedTotal)}
      />
      <ScoreCard
        label="Web Fundamentals"
        value={scores.technical}
        sub="Response codes, headers, delivery"
      />
      <ScoreCard label="AEO" value={scores.aeo} sub="Schema, structured data, AI-readiness" />
    </div>
  );
}

function scoreValues(
  summary: SiteHealthDashboard['score_summary'],
  pages: PageSummary[],
  analyzing: boolean,
): { overall: number | null; technical: number | null; aeo: number | null } {
  const incomplete =
    summary === null ||
    summary.overall_score === null ||
    summary.technical_score === null ||
    summary.aeo_score === null;
  const liveScores = analyzing && incomplete ? computeLiveScores(pages) : null;
  return {
    overall: summary?.overall_score ?? liveScores?.overall ?? null,
    technical: summary?.technical_score ?? liveScores?.technical ?? null,
    aeo: summary?.aeo_score ?? liveScores?.aeo ?? null,
  };
}

function overallSub(
  summary: SiteHealthDashboard['score_summary'],
  analyzing: boolean,
  crawl: SiteCrawl | null,
  selectedTotal: number | null,
): string {
  if (summary && summary.overall_score !== null) {
    return `Across ${summary.analyzed_count} of ${summary.selected_count} pages`;
  }
  if (analyzing && crawl) {
    return selectedTotal !== null
      ? `based on ${crawl.analyzed_count} of ${selectedTotal} pages`
      : `based on ${crawl.analyzed_count} pages so far`;
  }
  if (crawl && ['failed', 'cancelled', 'paused'].includes(crawl.status)) {
    return 'No score available';
  }
  return 'Scores appear as pages are analyzed';
}

/**
 * Running mean of the per-page scores that have landed so far. Only pages with
 * a completed analysis contribute; returns null (rendered as `—`) until at
 * least one page has scores — never a fabricated zero.
 */
function computeLiveScores(
  pages: PageSummary[],
): { overall: number | null; technical: number | null; aeo: number | null } | null {
  const scored = pages.filter((p) => p.overall_score !== null);
  if (scored.length === 0) return null;
  const mean = (pick: (p: PageSummary) => number | null) => {
    const values = scored.map(pick).filter((v): v is number => v !== null);
    if (values.length === 0) return null;
    return values.reduce((sum, v) => sum + v, 0) / values.length;
  };
  return {
    overall: mean((p) => p.overall_score),
    technical: mean((p) => p.technical_score),
    aeo: mean((p) => p.aeo_score),
  };
}

function ScoreCard({
  label,
  value,
  sub,
}: Readonly<{ label: string; value: number | null; sub: string }>) {
  return (
    <Card className="border-border/70">
      <CardContent className="flex items-center gap-4 p-5 sm:p-6">
        {value === null ? (
          <div className="border-border/60 text-muted mono size-score-ring flex items-center justify-center rounded-full border text-base">
            {PLACEHOLDER}
          </div>
        ) : (
          <ScoreRing value={value} size={72} label={`${label} score: ${Math.round(value)}`} />
        )}
        <div className="grid gap-1">
          <p className="text-muted text-xs font-semibold tracking-wider uppercase">{label}</p>
          <span className="font-display text-foreground text-xl font-semibold tabular-nums">
            {value === null ? PLACEHOLDER : `${formatScore(value)} / 100`}
          </span>
          <span className="text-muted text-xs leading-relaxed">{sub}</span>
        </div>
      </CardContent>
    </Card>
  );
}
