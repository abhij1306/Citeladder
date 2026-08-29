'use client';

import { useState } from 'react';
import Link from 'next/link';
import {
  ArrowUpRight,
  Check,
  ChevronRight,
  Copy,
  ExternalLink,
  FileText,
  HelpCircle,
  Sparkles,
  Split,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import type { DemandSignal } from '@/lib/api/demand';
import { contentBriefHref } from '@/lib/demand/content-brief';
import {
  competingPages,
  numericMetric,
  safePageUrl,
  signalTarget,
  signalTargetKind,
} from '@/lib/demand/signals';
import { availabilityLabel } from '@/lib/format';
import { cn } from '@/lib/utils';

const SIGNAL_METAS: Record<
  string,
  {
    label: string;
    variant: 'status' | 'neutral';
    statusValue?: 'success' | 'warning' | 'info' | 'danger';
    icon: typeof Sparkles;
  }
> = {
  striking_distance: {
    label: 'Striking distance',
    variant: 'status',
    statusValue: 'info',
    icon: ArrowUpRight,
  },
  query_cannibalization: {
    label: 'Cannibalization',
    variant: 'status',
    statusValue: 'warning',
    icon: Split,
  },
  property_relative_ctr_gap: {
    label: 'CTR gap',
    variant: 'status',
    statusValue: 'danger',
    icon: TrendingDown,
  },
  high_impression_low_ctr: {
    label: 'Low CTR',
    variant: 'status',
    statusValue: 'danger',
    icon: TrendingDown,
  },
  emerging_query: {
    label: 'Emerging',
    variant: 'status',
    statusValue: 'success',
    icon: TrendingUp,
  },
  declining_query: {
    label: 'Declining',
    variant: 'status',
    statusValue: 'danger',
    icon: TrendingDown,
  },
  branded_query_performance: {
    label: 'Branded cohort',
    variant: 'neutral',
    icon: HelpCircle,
  },
};

function formatCtr(signal: DemandSignal): string {
  const persistedCtr = numericMetric(signal, 'ctr');
  if (persistedCtr !== null) return `${(persistedCtr * 100).toFixed(1)}%`;
  const impressions = numericMetric(signal, 'impressions');
  const clicks = numericMetric(signal, 'clicks');
  if (impressions === null || clicks === null || impressions === 0)
    return availabilityLabel('not_measured');
  return `${((clicks / impressions) * 100).toFixed(1)}%`;
}

function formatCount(value: number | null): string {
  return value === null ? availabilityLabel('not_measured') : value.toLocaleString('en-US');
}

type DiagnosticInsight = {
  headline: string;
  detail: string;
  tone: 'info' | 'warning' | 'danger' | 'success' | 'neutral';
};

/**
 * The plain-language reading of a signal.
 *
 * Every figure quoted here must come from `signal.metrics`/`signal.evidence`.
 * When a metric was not observed the sentence drops it rather than
 * substituting a default — a page whose whole premise is "versioned GSC
 * evidence" cannot print a count it did not measure.
 */
function getDiagnosticInsight(signal: DemandSignal): DiagnosticInsight {
  return (DIAGNOSTIC_INSIGHTS[signal.signal_type] ?? defaultInsight)(signal);
}

const DIAGNOSTIC_INSIGHTS: Record<string, (signal: DemandSignal) => DiagnosticInsight> = {
  striking_distance: strikingDistanceInsight,
  query_cannibalization: cannibalizationInsight,
  property_relative_ctr_gap: ctrGapInsight,
  high_impression_low_ctr: ctrGapInsight,
  emerging_query: emergingInsight,
  declining_query: () => ({
    headline: 'Declining search momentum',
    detail:
      'Impressions fell across the last two 14-day windows. Review freshness and what now outranks you.',
    tone: 'danger',
  }),
  branded_query_performance: () => ({
    headline: 'Branded query cohort',
    detail:
      'Navigational demand for your brand, tracked separately so it cannot skew the organic gap analysis.',
    tone: 'neutral',
  }),
};

function strikingDistanceInsight(signal: DemandSignal): DiagnosticInsight {
  const position = numericMetric(signal, 'position');
  const impressions = numericMetric(signal, 'impressions');
  const observed = [
    position !== null ? `ranks #${position.toFixed(1)}` : null,
    impressions !== null ? `${impressions.toLocaleString('en-US')} impressions` : null,
  ].filter(Boolean);
  return {
    headline: 'Within reach of the top results',
    detail: observed.length
      ? `This query ${observed.join(' with ')} — close enough that better coverage can lift it into the positions that earn clicks.`
      : 'This query ranks close enough to the top results that better coverage can lift it into the positions that earn clicks.',
    tone: 'info',
  };
}

function cannibalizationInsight(signal: DemandSignal): DiagnosticInsight {
  const pages = competingPages(signal);
  return {
    headline:
      pages.length > 0 ? `${pages.length} competing URLs detected` : 'Competing URLs detected',
    detail:
      'More than one page on your domain ranks for this query, splitting its impressions between them.',
    tone: 'warning',
  };
}

function ctrGapInsight(signal: DemandSignal): DiagnosticInsight {
  const median = numericMetric(signal, 'cohort_median_ctr');
  const ctr = numericMetric(signal, 'ctr');
  const comparable = median !== null && ctr !== null;
  return {
    headline: 'Underperforming expected CTR',
    detail: comparable
      ? `A ${(ctr * 100).toFixed(1)}% click-through rate against a ${(median * 100).toFixed(1)}% median for this position band. The ranking is fine; the result is not being clicked.`
      : 'Impressions are not converting into clicks at the rate this ranking position usually earns.',
    tone: 'danger',
  };
}

function emergingInsight(signal: DemandSignal): DiagnosticInsight {
  const prior = numericMetric(signal, 'prior_impressions');
  const recent = numericMetric(signal, 'recent_impressions');
  const quotable = prior !== null && recent !== null && prior > 0;
  return {
    headline: 'Surging search momentum',
    detail: quotable
      ? `Impressions grew ${Math.round(((recent - prior) / prior) * 100)}% (+${(recent - prior).toLocaleString('en-US')}) across the last two 14-day windows.`
      : 'Impressions rose across the last two 14-day windows. A strong candidate for dedicated coverage.',
    tone: 'success',
  };
}

function defaultInsight(): DiagnosticInsight {
  return {
    headline: 'Search demand gap',
    detail: 'A Search Console gap identified by demand analysis.',
    tone: 'neutral',
  };
}

export function DemandSignalCard({
  signal,
  rank,
  onInspect,
}: Readonly<{
  signal: DemandSignal;
  rank: number;
  onInspect: (signal: DemandSignal) => void;
}>) {
  const [copied, setCopied] = useState(false);
  const targetKind = signalTargetKind(signal);
  const target = signalTarget(signal);
  const meta = SIGNAL_METAS[signal.signal_type] ?? {
    label: 'Demand signal',
    variant: 'neutral',
    icon: Sparkles,
  };
  const insight = getDiagnosticInsight(signal);
  const Icon = meta.icon;
  const pages = competingPages(signal);
  const linkablePageUrl = safePageUrl(signal.page_url);

  const copyTarget = async () => {
    try {
      await navigator.clipboard.writeText(target);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard write failed gracefully
    }
  };

  const insightToneClasses = {
    info: 'bg-info-bg/30 border-info-border/40 text-info-text',
    warning: 'bg-warning-bg/30 border-warning-border/40 text-warning-text',
    danger: 'bg-danger-bg/30 border-danger-border/40 text-danger-text',
    success: 'bg-success-bg/30 border-success-border/40 text-success-text',
    neutral: 'bg-well border-border-subtle text-secondary',
  }[insight.tone];

  return (
    <Card className="bg-panel border-border hover:border-border-strong transition-[border-color,box-shadow] hover:shadow-xs">
      <CardContent className="grid gap-4 p-4 sm:p-[var(--card-padding)]">
        {/* Header: Rank, Badges, Query Title */}
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <span className="bg-well text-muted flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums">
              #{rank}
            </span>
            <div className="grid min-w-0 flex-1 gap-1.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge variant="neutral">{targetKind}</Badge>
                {meta.variant === 'status' && meta.statusValue ? (
                  <Badge variant="status" value={meta.statusValue}>
                    {meta.label}
                  </Badge>
                ) : (
                  <Badge variant="neutral">{meta.label}</Badge>
                )}
              </div>
              <div className="flex items-center gap-2">
                <h3 className="text-foreground text-base leading-tight font-semibold break-words">
                  {target}
                </h3>
                <button
                  type="button"
                  onClick={copyTarget}
                  className="text-muted hover:text-foreground shrink-0 rounded p-0.5 transition-colors"
                  title="Copy search query"
                  aria-label="Copy query text"
                >
                  {copied ? (
                    <Check className="text-success size-3.5" />
                  ) : (
                    <Copy className="size-3.5" />
                  )}
                </button>
              </div>
              {linkablePageUrl && targetKind === 'Query' && (
                <div className="text-muted flex items-center gap-1.5 text-xs">
                  <span className="shrink-0">Target page:</span>
                  <a
                    href={linkablePageUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="text-accent-text inline-flex max-w-sm items-center gap-1 truncate hover:underline sm:max-w-md"
                  >
                    {linkablePageUrl}
                    <ExternalLink className="size-3" />
                  </a>
                </div>
              )}
            </div>
          </div>

          {/* Quick Action Buttons on Desktop */}
          <div className="flex shrink-0 items-center gap-2 self-end sm:self-start">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => onInspect(signal)}
              className="text-xs"
            >
              Inspect Evidence
            </Button>
          </div>
        </div>

        {/* Diagnostic Insight Callout */}
        <div className={cn('rounded-md border p-3 text-xs leading-relaxed', insightToneClasses)}>
          <div className="flex items-start gap-2">
            <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <div className="grid gap-0.5">
              <span className="font-semibold">{insight.headline}</span>
              <p className="opacity-90">{insight.detail}</p>
            </div>
          </div>

          {/* Competing URLs summary pill for cannibalization */}
          {pages.length > 0 && (
            <div className="mt-2.5 grid gap-1.5 border-t border-current/15 pt-2">
              <span className="text-2xs font-medium opacity-80">Competing URLs:</span>
              <div className="grid gap-1">
                {pages.slice(0, 2).map((page) => (
                  <div key={page.url} className="text-2xs flex items-center justify-between gap-2">
                    <span className="truncate opacity-90">{page.url}</span>
                    <span className="shrink-0 font-medium tabular-nums">
                      {page.impressions.toLocaleString('en-US')} imp (
                      {(page.share * 100).toFixed(0)}%)
                    </span>
                  </div>
                ))}
                {pages.length > 2 && (
                  <span className="text-2xs italic opacity-75">
                    +{pages.length - 2} more pages in drawer
                  </span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Metrics Bar & Next Steps */}
        <div className="border-border-subtle flex flex-col gap-3 border-t pt-3 sm:flex-row sm:items-center sm:justify-between">
          <dl className="grid flex-1 grid-cols-2 gap-3 sm:grid-cols-4">
            <div>
              <dt className="text-muted text-xs">Impressions</dt>
              <dd className="text-foreground mt-0.5 text-sm font-semibold tabular-nums">
                {formatCount(numericMetric(signal, 'impressions'))}
              </dd>
            </div>
            <div>
              <dt className="text-muted text-xs">Clicks</dt>
              <dd className="text-foreground mt-0.5 text-sm font-semibold tabular-nums">
                {formatCount(numericMetric(signal, 'clicks'))}
              </dd>
            </div>
            <div>
              <dt className="text-muted text-xs">CTR</dt>
              <dd className="text-foreground mt-0.5 text-sm font-semibold tabular-nums">
                {formatCtr(signal)}
              </dd>
            </div>
            <div>
              <dt className="text-muted text-xs">Avg Position</dt>
              <dd className="text-foreground mt-0.5 text-sm font-semibold tabular-nums">
                {numericMetric(signal, 'position')?.toFixed(1) ?? availabilityLabel('not_measured')}
              </dd>
            </div>
          </dl>

          {/* Direct Workflow Links */}
          <div className="flex shrink-0 items-center gap-2 self-end sm:self-auto">
            {signal.signal_type !== 'branded_query_performance' && (
              <Button
                variant="ghost"
                size="sm"
                asChild
                className="text-accent-text hover:bg-accent-soft text-xs"
              >
                <Link href="/opportunities" className="inline-flex items-center">
                  <span>Opportunities</span>
                  <ChevronRight className="ml-1 size-3" />
                </Link>
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              asChild
              className="text-accent-text hover:bg-accent-soft text-xs"
            >
              <Link href={contentBriefHref(signal)} className="inline-flex items-center">
                <FileText className="mr-1 size-3" />
                <span>Draft</span>
              </Link>
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
