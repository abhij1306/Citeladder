'use client';

import Link from 'next/link';
import { ArrowUpRight, ExternalLink, FileText, ShieldCheck, Split } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Drawer } from '@/components/ui/drawer';
import type { DemandSignal } from '@/lib/api/demand';
import { contentBriefHref } from '@/lib/demand/content-brief';
import {
  competingPages,
  numericMetric,
  safePageUrl,
  signalTarget,
  signalTargetKind,
} from '@/lib/demand/signals';
import { formatWindowDate } from '@/lib/format';

export function DemandEvidenceDrawer({
  signal,
  open,
  onOpenChange,
}: Readonly<{
  signal: DemandSignal | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}>) {
  if (!signal) return null;

  const targetKind = signalTargetKind(signal);
  const target = signalTarget(signal);
  const metrics = signal.metrics;
  const evidence = signal.evidence;

  const pages = competingPages(signal);

  // Cohort details for CTR gap
  const cohortMedianCtr = numericMetric(signal, 'cohort_median_ctr');
  // The band label appends `.0`/`.9`, so only a whole number produces a valid
  // range — a fractional 7.5 would otherwise render "Positions 7.5.0 – 7.5.9".
  const rawBand = evidence.position_band;
  const positionBand =
    typeof rawBand === 'number' && Number.isFinite(rawBand) ? Math.floor(rawBand) : null;
  const linkablePageUrl = safePageUrl(signal.page_url);

  // Source provenance
  const metricRowIds = Array.isArray(evidence.source_metric_row_ids)
    ? (evidence.source_metric_row_ids as string[])
    : [];
  const artifactIds = Array.isArray(evidence.source_artifact_ids)
    ? (evidence.source_artifact_ids as string[])
    : [];

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="Demand Signal Evidence"
      className="max-w-md sm:max-w-lg"
      bodyClassName="px-4 py-3"
      footer={
        <div className="border-border-subtle flex flex-wrap items-center justify-between gap-2 border-t pt-3">
          <Button variant="secondary" size="sm" asChild>
            <Link href="/opportunities" className="inline-flex items-center">
              <ArrowUpRight className="mr-1.5 size-3.5" />
              View in Opportunities
            </Link>
          </Button>
          <Button variant="primary" size="sm" asChild>
            <Link href={contentBriefHref(signal)} className="inline-flex items-center">
              <FileText className="mr-1.5 size-3.5" />
              Draft Content Brief
            </Link>
          </Button>
        </div>
      }
    >
      <div className="grid gap-5">
        {/* Header Info */}
        <div className="border-border-subtle grid gap-2 border-b pb-4">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="neutral">{targetKind}</Badge>
            <Badge variant="status" value="info">
              {signal.signal_type.replace(/_/g, ' ')}
            </Badge>
          </div>
          <h2 className="text-foreground text-base font-semibold break-words">{target}</h2>
          {linkablePageUrl && (
            <div className="text-muted flex items-center gap-1.5 text-xs">
              <span className="shrink-0 font-medium">Resolved URL:</span>
              <a
                href={linkablePageUrl}
                target="_blank"
                rel="noreferrer"
                className="text-accent-text inline-flex items-center gap-1 truncate hover:underline"
              >
                {linkablePageUrl}
                <ExternalLink className="size-3" />
              </a>
            </div>
          )}
        </div>

        {/* Observed GSC Metrics */}
        <section className="grid gap-2">
          <h3 className="text-muted text-xs font-semibold tracking-wider uppercase">
            Observed GSC Performance
          </h3>
          <div className="border-border bg-panel grid grid-cols-2 gap-2 rounded-md border p-3 sm:grid-cols-4">
            <div>
              <span className="text-2xs text-muted">Impressions</span>
              <p className="text-foreground text-sm font-semibold tabular-nums">
                {typeof metrics.impressions === 'number'
                  ? metrics.impressions.toLocaleString()
                  : '—'}
              </p>
            </div>
            <div>
              <span className="text-2xs text-muted">Clicks</span>
              <p className="text-foreground text-sm font-semibold tabular-nums">
                {typeof metrics.clicks === 'number' ? metrics.clicks.toLocaleString() : '—'}
              </p>
            </div>
            <div>
              <span className="text-2xs text-muted">CTR</span>
              <p className="text-foreground text-sm font-semibold tabular-nums">
                {typeof metrics.ctr === 'number' ? `${(metrics.ctr * 100).toFixed(1)}%` : '—'}
              </p>
            </div>
            <div>
              <span className="text-2xs text-muted">Avg Position</span>
              <p className="text-foreground text-sm font-semibold tabular-nums">
                {typeof metrics.position === 'number' ? metrics.position.toFixed(1) : '—'}
              </p>
            </div>
          </div>
        </section>

        {/* Cannibalization Breakdown if applicable */}
        {pages.length > 0 && (
          <section className="grid gap-2">
            <div className="text-muted flex items-center gap-1.5 text-xs font-semibold tracking-wider uppercase">
              <Split className="text-warning size-3.5" />
              <span>Competing URL Breakdown ({pages.length} Pages)</span>
            </div>
            <div className="border-border bg-panel divide-border-subtle divide-y rounded-md border">
              {pages.map((page) => (
                <div key={page.url} className="p-2.5 text-xs">
                  <div className="text-foreground font-medium break-all">{page.url}</div>
                  <div className="text-muted text-2xs mt-1 flex items-center justify-between">
                    <span>{page.impressions.toLocaleString('en-US')} impressions</span>
                    <span className="text-foreground font-semibold tabular-nums">
                      {(page.share * 100).toFixed(0)}% query share
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* CTR Gap Cohort Benchmark if applicable */}
        {cohortMedianCtr !== null && (
          <section className="grid gap-2">
            <h3 className="text-muted text-xs font-semibold tracking-wider uppercase">
              Position Cohort Benchmark
            </h3>
            <div className="border-border bg-panel grid gap-2 rounded-md border p-3 text-xs">
              <div className="flex justify-between">
                <span className="text-muted">Position Band:</span>
                <span className="text-foreground font-medium">
                  {positionBand !== null ? `Positions ${positionBand}.0 – ${positionBand}.9` : '—'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Cohort Median CTR:</span>
                <span className="text-success font-semibold tabular-nums">
                  {(cohortMedianCtr * 100).toFixed(1)}%
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Observed Actual CTR:</span>
                <span className="text-danger font-semibold tabular-nums">
                  {/* An unobserved CTR is "—", never a fabricated 0.0%. */}
                  {numericMetric(signal, 'ctr') !== null
                    ? `${(numericMetric(signal, 'ctr')! * 100).toFixed(1)}%`
                    : '—'}
                </span>
              </div>
            </div>
          </section>
        )}

        {/* Provenance & Audit Info */}
        <section className="border-border-subtle grid gap-2 border-t pt-3">
          <div className="text-muted flex items-center gap-1.5 text-xs font-semibold tracking-wider uppercase">
            <ShieldCheck className="text-accent size-3.5" />
            <span>Audit Trail & Provenance</span>
          </div>
          <div className="border-border bg-well text-2xs text-muted grid gap-1.5 rounded-md border p-3">
            <div className="flex justify-between">
              <span>Signal ID:</span>
              <span className="text-foreground font-mono">{signal.id.slice(0, 8)}...</span>
            </div>
            <div className="flex justify-between">
              <span>Snapshot ID:</span>
              <span className="text-foreground font-mono">{signal.snapshot_id.slice(0, 8)}...</span>
            </div>
            <div className="flex justify-between">
              <span>Source Metric Rows:</span>
              <span className="text-foreground">{metricRowIds.length} rows linked</span>
            </div>
            <div className="flex justify-between">
              <span>Source Artifacts:</span>
              <span className="text-foreground">{artifactIds.length} artifacts</span>
            </div>
            <div className="flex justify-between">
              <span>Evaluated:</span>
              <span className="text-foreground">{formatWindowDate(signal.created_at)}</span>
            </div>
          </div>
        </section>
      </div>
    </Drawer>
  );
}
