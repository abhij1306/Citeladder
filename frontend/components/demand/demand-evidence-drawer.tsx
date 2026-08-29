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
import { availabilityLabel, formatWindowDate } from '@/lib/format';

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
  return <DemandEvidenceContent signal={signal} open={open} onOpenChange={onOpenChange} />;
}

function DemandEvidenceContent({
  signal,
  open,
  onOpenChange,
}: Readonly<{
  signal: DemandSignal;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}>) {
  const details = demandEvidenceDetails(signal);

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
      <div className="grid gap-[var(--workspace-gap)]">
        {/* Header Info */}
        <div className="border-border-subtle grid gap-2 border-b pb-4">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="neutral">{details.targetKind}</Badge>
            <Badge variant="status" value="info">
              {signal.signal_type.replace(/_/g, ' ')}
            </Badge>
          </div>
          <h2 className="text-foreground text-base font-semibold break-words">{details.target}</h2>
          {details.linkablePageUrl && (
            <div className="text-muted flex items-center gap-1.5 text-xs">
              <span className="shrink-0 font-medium">Resolved URL:</span>
              <a
                href={details.linkablePageUrl}
                target="_blank"
                rel="noreferrer"
                className="text-accent-text inline-flex items-center gap-1 truncate hover:underline"
              >
                {details.linkablePageUrl}
                <ExternalLink className="size-3" />
              </a>
            </div>
          )}
        </div>

        {/* Observed GSC Metrics */}
        <section className="grid gap-2">
          <h3 className="text-muted text-xs font-semibold">Observed GSC Performance</h3>
          <div className="border-border bg-panel grid grid-cols-2 gap-2 rounded-md border p-3 sm:grid-cols-4">
            <div>
              <span className="text-2xs text-muted">Impressions</span>
              <p className="text-foreground text-sm font-semibold tabular-nums">
                {typeof details.metrics.impressions === 'number'
                  ? details.metrics.impressions.toLocaleString()
                  : availabilityLabel('not_measured')}
              </p>
            </div>
            <div>
              <span className="text-2xs text-muted">Clicks</span>
              <p className="text-foreground text-sm font-semibold tabular-nums">
                {typeof details.metrics.clicks === 'number'
                  ? details.metrics.clicks.toLocaleString()
                  : availabilityLabel('not_measured')}
              </p>
            </div>
            <div>
              <span className="text-2xs text-muted">CTR</span>
              <p className="text-foreground text-sm font-semibold tabular-nums">
                {typeof details.metrics.ctr === 'number'
                  ? `${(details.metrics.ctr * 100).toFixed(1)}%`
                  : availabilityLabel('not_measured')}
              </p>
            </div>
            <div>
              <span className="text-2xs text-muted">Avg Position</span>
              <p className="text-foreground text-sm font-semibold tabular-nums">
                {typeof details.metrics.position === 'number'
                  ? details.metrics.position.toFixed(1)
                  : availabilityLabel('not_measured')}
              </p>
            </div>
          </div>
        </section>

        {/* Cannibalization Breakdown if applicable */}
        {details.pages.length > 0 && (
          <section className="grid gap-2">
            <div className="text-muted flex items-center gap-1.5 text-xs font-semibold">
              <Split className="text-warning size-3.5" />
              <span>Competing URL Breakdown ({details.pages.length} Pages)</span>
            </div>
            <div className="border-border bg-panel divide-border-subtle divide-y rounded-md border">
              {details.pages.map((page) => (
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
        {details.cohortMedianCtr !== null && (
          <section className="grid gap-2">
            <h3 className="text-muted text-xs font-semibold">Position Cohort Benchmark</h3>
            <div className="border-border bg-panel grid gap-2 rounded-md border p-3 text-xs">
              <div className="flex justify-between">
                <span className="text-muted">Position Band:</span>
                <span className="text-foreground font-medium">
                  {details.positionBand !== null
                    ? `Positions ${details.positionBand}.0 – ${details.positionBand}.9`
                    : availabilityLabel('not_measured')}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Cohort Median CTR:</span>
                <span className="text-success font-semibold tabular-nums">
                  {(details.cohortMedianCtr * 100).toFixed(1)}%
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Observed Actual CTR:</span>
                <span className="text-danger font-semibold tabular-nums">
                  {/* An unobserved CTR is explicit, never a fabricated 0.0%. */}
                  {numericMetric(signal, 'ctr') !== null
                    ? `${(numericMetric(signal, 'ctr')! * 100).toFixed(1)}%`
                    : availabilityLabel('not_measured')}
                </span>
              </div>
            </div>
          </section>
        )}

        {/* Provenance & Audit Info */}
        <section className="border-border-subtle grid gap-2 border-t pt-3">
          <div className="text-muted flex items-center gap-1.5 text-xs font-semibold">
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
              <span className="text-foreground">{details.metricRowIds.length} rows linked</span>
            </div>
            <div className="flex justify-between">
              <span>Source Artifacts:</span>
              <span className="text-foreground">{details.artifactIds.length} artifacts</span>
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

function demandEvidenceDetails(signal: DemandSignal) {
  const evidence = signal.evidence;
  const rawBand = evidence.position_band;
  return {
    targetKind: signalTargetKind(signal),
    target: signalTarget(signal),
    metrics: signal.metrics,
    pages: competingPages(signal),
    cohortMedianCtr: numericMetric(signal, 'cohort_median_ctr'),
    positionBand:
      typeof rawBand === 'number' && Number.isFinite(rawBand) ? Math.floor(rawBand) : null,
    linkablePageUrl: safePageUrl(signal.page_url),
    metricRowIds: Array.isArray(evidence.source_metric_row_ids)
      ? (evidence.source_metric_row_ids as string[])
      : [],
    artifactIds: Array.isArray(evidence.source_artifact_ids)
      ? (evidence.source_artifact_ids as string[])
      : [],
  };
}
