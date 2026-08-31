import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ScoreRing } from '@/components/ui/score-ring';
import { UnavailableValue } from '@/components/ui/unavailable-value';
import { ICONS } from '@/lib/icons';
import type { SiteCrawl, SiteHealthDashboard, SiteHealthOverview } from '@/lib/api/types';
import { PLACEHOLDER } from '@/lib/site-health/status';

type Summary = SiteHealthDashboard['score_summary'];
type MetricContext = {
  overview?: SiteHealthOverview;
  summary: Summary;
  analyzed: number;
  selected: number;
  classificationState: SiteHealthOverview['classification_state'] | undefined;
};
type MetricModel = {
  title: string;
  value: number | null;
  coverage: number | null;
  coverageUnit?: 'analyzed' | 'measured';
  confidence: string;
  detail: string;
  href: string;
  icon: typeof ICONS.site;
};

function confidence(state: string | undefined): string {
  if (state === 'measured') return 'High confidence';
  if (state === 'limited_evidence') return 'Moderate confidence';
  if (state === 'excluded') return 'Excluded';
  return 'Low confidence';
}

function percentRatio(value: number | null | undefined): number | null {
  return value === null || value === undefined ? null : value * 100;
}

export function OverviewMetricCards({
  overview,
  dashboard,
  crawl,
}: Readonly<{
  overview?: SiteHealthOverview;
  dashboard: SiteHealthDashboard | undefined;
  crawl: SiteCrawl | null;
}>) {
  const context = metricContext(overview, dashboard, crawl);
  const metrics = [
    technicalMetric(context),
    aeoMetric(context),
    measurementMetric(context),
    crawlMetric(context),
  ];
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4" data-testid="overview-metrics">
      {metrics.map((metric) => (
        <OverviewMetricCard key={metric.title} {...metric} />
      ))}
    </div>
  );
}

function metricContext(
  overview: SiteHealthOverview | undefined,
  dashboard: SiteHealthDashboard | undefined,
  crawl: SiteCrawl | null,
): MetricContext {
  const summary: Summary = dashboard?.score_summary ?? crawl?.score_summary ?? null;
  return {
    overview,
    summary,
    analyzed: overview?.audited_page_count ?? summary?.analyzed_count ?? crawl?.analyzed_count ?? 0,
    selected:
      overview?.selected_page_count ?? summary?.selected_count ?? crawl?.visible_url_count ?? 0,
    classificationState: overview?.classification_state ?? summary?.classification_state,
  };
}

function technicalMetric(context: MetricContext): MetricModel {
  const source = context.overview ?? context.summary;
  const score = source?.web_fundamentals_score;
  const coverage = source?.web_fundamentals_coverage;
  const state = source?.web_fundamentals_state;
  return {
    title: 'Web Fundamentals',
    value: score ?? null,
    coverage: coverage ?? null,
    confidence: confidence(state),
    detail: context.overview
      ? occurrenceDetail(
          context.overview.technical_defect_count,
          'defect',
          context.overview.technical_defect_affected_page_count,
        )
      : `${context.analyzed} pages analyzed`,
    href: '/issues?dimension=technical',
    icon: ICONS.siteHealth,
  };
}

function aeoMetric(context: MetricContext): MetricModel {
  const source = context.overview ?? context.summary;
  const score = source?.aeo_readiness_score;
  const coverage = source?.aeo_measurement_coverage;
  const state = source?.aeo_measurement_state;
  return {
    title:
      context.classificationState === 'complete'
        ? 'AEO Readiness'
        : 'Readiness of classified audited pages',
    value: score ?? null,
    coverage: coverage ?? null,
    confidence: confidence(state),
    detail: context.overview
      ? occurrenceDetail(
          context.overview.aeo_readiness_gap_count,
          'readiness gap',
          context.overview.aeo_readiness_gap_affected_page_count,
        )
      : `${context.analyzed} pages analyzed`,
    href: '/issues?dimension=aeo',
    icon: ICONS.visibility,
  };
}

function occurrenceDetail(count: number, noun: string, affectedPages: number): string {
  const occurrenceLabel = count === 1 ? `${noun} occurrence` : `${noun} occurrences`;
  const pageLabel = affectedPages === 1 ? 'page' : 'pages';
  return `${count} ${occurrenceLabel} · ${affectedPages} ${pageLabel} affected`;
}

function measurementMetric(context: MetricContext): MetricModel {
  const source = context.overview ?? context.summary;
  const coverage = source?.aeo_measurement_coverage;
  const state = source?.aeo_measurement_state;
  return {
    title: 'AEO Measurement Coverage',
    value: percentRatio(coverage),
    coverage: coverage ?? null,
    confidence: confidence(state),
    detail: context.overview
      ? `${context.overview.measured_check_count} of ${context.overview.expected_check_count} checks measured`
      : 'Determinate evidence across applicable pillars',
    href: '/site?tab=aeo-readiness',
    icon: ICONS.reports,
  };
}

function crawlMetric(context: MetricContext): MetricModel {
  const progress = context.selected > 0 ? (100 * context.analyzed) / context.selected : null;
  const terminalCoverage = context.overview?.crawl_coverage;
  return {
    title: 'Crawl Coverage',
    value: progress,
    coverage: progress === null ? null : progress / 100,
    coverageUnit: 'analyzed',
    confidence: terminalCoverage ? coverageStateLabel(terminalCoverage.state) : 'In progress',
    detail: terminalCoverage
      ? `${context.analyzed} of ${context.selected || PLACEHOLDER} pages analyzed${coverageReason(terminalCoverage.evidence)}`
      : `${context.analyzed} of ${context.selected || PLACEHOLDER} pages analyzed`,
    href: '/site?tab=pages',
    icon: ICONS.site,
  };
}

function coverageStateLabel(state: string): string {
  if (state === 'complete') return 'Complete coverage';
  if (state === 'partial') return 'Partial coverage';
  return 'Coverage unknown';
}

function coverageReason(evidence: Record<string, unknown>): string {
  const reasons = evidence.reasons;
  if (!Array.isArray(reasons)) return '';
  const reason = reasons.find((value): value is string => typeof value === 'string');
  return reason ? ` · ${reason.replaceAll('_', ' ')}` : '';
}

function OverviewMetricCard({
  title,
  value,
  coverage,
  coverageUnit = 'measured',
  confidence: confidenceLabel,
  detail,
  href,
  icon: Icon,
}: Readonly<MetricModel>) {
  const coverageLabel =
    coverage === null ? 'Not measured' : `${Math.round(coverage * 100)}% ${coverageUnit}`;
  return (
    <Card>
      <CardContent className="grid h-full gap-4 p-[var(--card-padding)]">
        <div className="flex items-start justify-between gap-3">
          <div className="grid gap-1">
            <Icon aria-hidden className="text-accent size-5" />
            <p className="text-foreground text-sm font-medium">{title}</p>
          </div>
          {value === null ? (
            <UnavailableValue state="not_measured" />
          ) : (
            <ScoreRing value={value} size={64} label={`${title} score: ${Math.round(value)}`} />
          )}
        </div>
        <div className="grid gap-1">
          <p className="text-muted text-xs">
            {coverageLabel} · {confidenceLabel}
          </p>
          <p className="text-secondary text-xs">{detail}</p>
        </div>
        <Button asChild variant="secondary" size="sm" className="mt-auto justify-self-start">
          <Link href={href}>View details</Link>
        </Button>
      </CardContent>
    </Card>
  );
}
