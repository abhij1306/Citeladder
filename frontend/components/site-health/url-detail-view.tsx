import { useState } from 'react';
import Link from 'next/link';
import { ChevronDown, ChevronRight } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ScoreRing } from '@/components/ui/score-ring';
import { Label, displayHeadingXlClasses } from '@/components/ui/typography';
import { InternalLinksCard } from '@/components/site-health/internal-links-card';
import { PageKindBadge } from '@/components/site-health/page-kind-badge';
import type { DeliveryFacts, PageDetail, SiteIssue } from '@/lib/api/types';
import { ICONS } from '@/lib/icons';
import {
  pageKindConfidenceLabel,
  pageKindLabel,
  pageTraitLabel,
  readPageKindEvidence,
  type PageKindEvidenceView,
} from '@/lib/site-health/page-kinds';
import {
  dimensionLabel,
  issueTitle,
  severityBadgeValue,
  severityLabel,
  severityRank,
} from '@/lib/site-health/issues';
import {
  PLACEHOLDER,
  formatAudited,
  pageDisplayTitle,
  pageStatusBadgeValue,
  statusLabel,
} from '@/lib/site-health/status';
import { cn } from '@/lib/utils';

export function UrlDetailView({
  detail,
  rerunPending,
  rerunQueued,
  onRerun,
}: Readonly<{
  detail: PageDetail;
  rerunPending: boolean;
  rerunQueued: boolean;
  onRerun: () => void;
}>) {
  return (
    <>
      <nav className="text-muted text-xs" aria-label="Breadcrumb">
        <Link href="/site" className="hover:text-accent">
          Website
        </Link>
        <span className="px-1.5" aria-hidden>
          /
        </span>
        <span className="text-secondary break-all">
          {pageDisplayTitle(detail.title, detail.display_url)}
        </span>
      </nav>
      <HeaderCard
        detail={detail}
        rerunPending={rerunPending}
        rerunQueued={rerunQueued}
        onRerun={onRerun}
      />
      <div className="grid gap-4 sm:grid-cols-3">
        <ScoreTile
          label="Web Fundamentals"
          value={detail.web_fundamentals_score}
          coverage={detail.web_fundamentals_coverage}
          state={detail.web_fundamentals_state}
        />
        <ScoreTile
          label="AEO Readiness"
          value={detail.aeo_readiness_score}
          coverage={detail.aeo_measurement_coverage}
          state={detail.aeo_measurement_state}
        />
        <ScoreTile
          label="AEO Measurement Coverage"
          value={
            detail.aeo_measurement_coverage === null ? null : detail.aeo_measurement_coverage * 100
          }
          coverage={detail.aeo_measurement_coverage}
          state={detail.aeo_measurement_state}
        />
      </div>
      <DeliveryMetrics delivery={detail.delivery} />
      <InternalLinksCard links={detail.internal_links} crawlId={detail.crawl_id} />
      <IssuesList issues={detail.issues} />
    </>
  );
}

function HeaderCard({
  detail,
  rerunPending,
  rerunQueued,
  onRerun,
}: Readonly<{
  detail: PageDetail;
  rerunPending: boolean;
  rerunQueued: boolean;
  onRerun: () => void;
}>) {
  const pageKindEvidence = readPageKindEvidence(detail.page_kind_evidence, detail.page_kind);
  const [evidenceOpen, setEvidenceOpen] = useState(false);

  return (
    <Card>
      <CardContent className="grid gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="grid min-w-0 gap-1">
            <h1 className={cn(displayHeadingXlClasses, 'break-all')}>
              {pageDisplayTitle(detail.title, detail.display_url)}
            </h1>
          </div>
          <Button size="sm" onClick={onRerun} disabled={rerunPending}>
            {rerunPending ? 'Re-auditing…' : rerunQueued ? 'Re-audit queued' : 'Re-audit this page'}
          </Button>
        </div>
        <div className="text-secondary flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
          <span className="flex min-w-0 items-center gap-1.5">
            <Label>URL</Label>
            <a
              href={detail.display_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mono text-accent-text min-w-0 break-all hover:underline"
            >
              {detail.display_url}
            </a>
          </span>
          <PageTraits traits={detail.page_traits} />
          <span className="flex items-center gap-1.5">
            <Label>Page Kind</Label>
            <PageKindBadge pageKind={detail.page_kind} />
            {pageKindEvidence ? (
              <button
                type="button"
                aria-expanded={evidenceOpen}
                aria-controls="page-kind-evidence"
                aria-label={
                  pageKindEvidence.schemaConflict
                    ? 'Why this page kind? Schema markup disagrees.'
                    : 'Why this page kind?'
                }
                onClick={() => setEvidenceOpen((open) => !open)}
                className="text-accent-text inline-flex items-center gap-1 text-xs font-medium"
              >
                {evidenceOpen ? (
                  <ChevronDown className="size-3" aria-hidden />
                ) : (
                  <ChevronRight className="size-3" aria-hidden />
                )}
                Why this page kind?
                {pageKindEvidence.schemaConflict ? (
                  <span
                    className="bg-warning ms-0.5 inline-block size-1.25 rounded-full"
                    aria-hidden
                  />
                ) : null}
              </button>
            ) : null}
          </span>
          <span className="flex items-center gap-1.5">
            <Label>Last Audit</Label>
            <span>{formatAudited(detail.last_audited)}</span>
          </span>
          <span className="flex items-center gap-1.5">
            <Label>Status</Label>
            <Badge variant="status" value={pageStatusBadgeValue(detail.analysis_status)}>
              {statusLabel(detail.analysis_status)}
            </Badge>
          </span>
        </div>
        {pageKindEvidence && evidenceOpen ? (
          <PageKindEvidencePanel evidence={pageKindEvidence} finalPageKind={detail.page_kind} />
        ) : null}
      </CardContent>
    </Card>
  );
}

/**
 * Observed traits, shown beside the page kind.
 *
 * A kind is exclusive and answers "what is this page for". A trait is
 * additive and answers "what else is on it", so a product page carrying an
 * FAQ shows both rather than being filed as one or the other. Rendered only
 * when something was actually observed: an empty list is a real answer, not a
 * gap worth a placeholder row.
 */
function PageTraits({ traits }: Readonly<{ traits: readonly string[] | null }>) {
  if (traits === null || traits.length === 0) return null;
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <Label>Also on this page</Label>
      {traits.map((trait) => (
        <Badge key={trait}>{pageTraitLabel(trait)}</Badge>
      ))}
    </span>
  );
}

function PageKindEvidencePanel({
  evidence,
  finalPageKind,
}: Readonly<{ evidence: PageKindEvidenceView; finalPageKind: string | null }>) {
  const WarningIcon = ICONS.warning;
  return (
    <div id="page-kind-evidence">
      <div className="border-border-subtle bg-background-alt grid gap-3 rounded-lg border p-3">
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
          <EvidenceFact label="Classified by" value={evidence.classifiedBy} />
          <EvidenceFact
            label="Confidence"
            value={pageKindConfidenceLabel(evidence.confidence, evidence.tier)}
          />
          <EvidenceFact
            label="Schema suggests"
            value={
              evidence.schemaSuggestedType === null
                ? PLACEHOLDER
                : pageKindLabel(evidence.schemaSuggestedType)
            }
            warning={evidence.schemaConflict}
          />
          <EvidenceFact label="Signals matched" value={String(evidence.signals.length)} />
        </div>
        {evidence.otherReason !== null ? (
          <div
            role="note"
            className="border-border-subtle text-secondary rounded-sm border px-3 py-2 text-sm"
          >
            {evidence.otherReason === 'schema_only'
              ? 'Schema suggested a type, but no independent page evidence confirmed it, so the type was left unassigned.'
              : evidence.otherReason === 'conflicting_top_tier_evidence'
                ? 'Independent evidence disagreed at the same confidence tier, so the type was left unassigned.'
                : 'No classification signals matched this page, so its type was left unassigned rather than guessed.'}
          </div>
        ) : null}
        {evidence.alternatives.length > 0 ? (
          <section className="grid gap-1">
            <Label>Other candidates</Label>
            <div className="flex flex-wrap items-center gap-1.5">
              {evidence.alternatives.map((candidate) => (
                <span key={candidate.pageKind} className="flex items-center gap-1">
                  <Badge>{pageKindLabel(candidate.pageKind)}</Badge>
                  <span className="mono text-2xs text-muted">{candidate.tier}</span>
                </span>
              ))}
            </div>
          </section>
        ) : null}
        {evidence.conflicts.length > 0 ? (
          <section className="grid gap-1">
            <Label>Disagreeing signals</Label>
            {evidence.conflicts.map((conflict) => (
              <span
                key={`${conflict.signal}:${conflict.conflictingPageKind}`}
                className="text-secondary text-sm"
              >
                <span className="mono">{conflict.signal}</span> suggested{' '}
                <span className="mono">{pageKindLabel(conflict.conflictingPageKind)}</span>
                {conflict.detail ? <span className="text-muted"> ({conflict.detail})</span> : null}
              </span>
            ))}
          </section>
        ) : null}
        {evidence.schemaConflict && evidence.schemaSuggestedType !== null ? (
          <div
            role="note"
            className="border-warning-border bg-warning-bg text-warning-text flex items-start gap-2 rounded-sm border px-3 py-2 text-sm"
          >
            <WarningIcon className="mt-0.5 size-4 shrink-0" aria-hidden />
            <div>
              Schema markup on this page declares{' '}
              <span className="mono">{pageKindLabel(evidence.schemaSuggestedType)}</span>, which
              disagrees with the chosen type. URL and content signals outrank schema, so the page is
              treated as {finalPageKind === null ? PLACEHOLDER : pageKindLabel(finalPageKind)} —
              check whether the markup belongs here.
            </div>
          </div>
        ) : null}
        {evidence.signals.length > 0 ? <EvidenceSignals evidence={evidence} /> : null}
        <p className="text-2xs text-muted">
          Signals are evaluated in a fixed priority order; the highest-priority match sets the type.
        </p>
      </div>
    </div>
  );
}

function EvidenceFact({
  label,
  value,
  warning = false,
}: Readonly<{ label: string; value: string; warning?: boolean }>) {
  return (
    <span className="grid gap-0.5">
      <Label>{label}</Label>
      <span
        className={cn(
          'mono text-sm font-medium',
          warning ? 'text-warning-text' : 'text-foreground',
        )}
      >
        {value}
      </span>
    </span>
  );
}

function EvidenceSignals({ evidence }: Readonly<{ evidence: PageKindEvidenceView }>) {
  return (
    <div className="grid">
      {evidence.signals.map((signal, index) => {
        const chosen = signal.signal === evidence.classifiedBy;
        return (
          <div
            key={signal.signal}
            className="border-border-subtle flex flex-wrap items-center gap-x-3 gap-y-1 border-b py-1.5 last:border-b-0"
          >
            <span className="mono text-muted w-4.5 shrink-0 text-xs">{index + 1}</span>
            <span className={cn('mono text-sm', chosen ? 'text-foreground' : 'text-secondary')}>
              {signal.signal}
              {chosen ? (
                <span className="text-2xs text-accent-text ms-1.5 font-medium">chosen</span>
              ) : null}
            </span>
            <Badge>{pageKindLabel(signal.pageKind)}</Badge>
            <span
              className={cn(
                'mono text-sm font-medium',
                chosen ? 'text-foreground' : 'text-secondary',
              )}
            >
              {signal.tier}
            </span>
            <span className="flex min-w-0 flex-1 items-center gap-3">
              <span className="mono text-muted truncate text-xs" title={signal.detail}>
                {signal.detail}
              </span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

function ScoreTile({
  label,
  value,
  coverage,
  state,
}: Readonly<{ label: string; value: number | null; coverage: number | null; state: string }>) {
  const coverageLabel =
    coverage === null ? 'Coverage unavailable' : `${Math.round(coverage * 100)}% measured`;
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-2 py-[var(--card-padding)]">
        {value === null ? (
          <div className="mono border-border-subtle text-muted flex size-16 items-center justify-center rounded-full border text-base">
            {scoreStateLabel(state)}
          </div>
        ) : (
          <ScoreRing value={value} size={64} label={`${label}: ${Math.round(value)}`} />
        )}
        <Label>{label}</Label>
        <span className="text-muted text-center text-xs">
          {coverageLabel} · {scoreConfidenceLabel(state)}
        </span>
      </CardContent>
    </Card>
  );
}

function scoreStateLabel(state: string): string {
  if (state === 'limited_evidence') return 'Limited';
  if (state === 'excluded') return 'Excluded';
  return PLACEHOLDER;
}

function scoreConfidenceLabel(state: string): string {
  if (state === 'measured') return 'High confidence';
  if (state === 'limited_evidence') return 'Moderate confidence';
  if (state === 'excluded') return 'Excluded';
  return 'Not measured';
}

function DeliveryMetrics({ delivery }: Readonly<{ delivery: DeliveryFacts }>) {
  const items = [
    { label: 'TTFB', value: formatMeasuredMs(delivery.ttfb_ms) },
    { label: 'Response Size', value: formatBytes(delivery.decoded_bytes ?? delivery.html_bytes) },
    {
      label: 'HTTP Status',
      value: delivery.status_code === null ? PLACEHOLDER : `${delivery.status_code}`,
    },
    { label: 'Compression', value: delivery.compression ?? 'none' },
    { label: 'HTTP Version', value: delivery.http_version ?? PLACEHOLDER },
    { label: 'Cache-Control', value: delivery.cache_control ?? PLACEHOLDER },
    {
      label: 'Blocking Resources',
      value:
        delivery.blocking_resource_count === null
          ? PLACEHOLDER
          : `${delivery.blocking_resource_count}`,
    },
    { label: 'Wire Size', value: formatBytes(delivery.wire_bytes) },
  ];
  return (
    <Card>
      <CardContent className="grid gap-4">
        <div className="flex items-center justify-between">
          <h2 className="text-foreground text-base font-semibold tracking-[-0.015em]">
            Delivery Metrics
          </h2>
          <span className="text-2xs text-muted">
            Static HTTP-level measurements (not browser-rendered Core Web Vitals)
          </span>
        </div>
        <dl className="grid gap-4 sm:grid-cols-4">
          {items.map((item) => (
            <div key={item.label} className="grid gap-0.5">
              <Label>{item.label}</Label>
              <dd className="mono text-foreground text-sm font-medium">{item.value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

function IssuesList({ issues }: Readonly<{ issues: SiteIssue[] }>) {
  const ordered = [...issues].sort((a, b) => severityRank(a.severity) - severityRank(b.severity));
  return (
    <Card>
      <CardContent className="grid gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-foreground text-base font-semibold tracking-[-0.015em]">
            All Issues ({issues.length})
          </h2>
          <span className="text-2xs text-muted">Sorted by severity</span>
        </div>
        {ordered.length === 0 ? (
          <p className="text-secondary text-sm">No issues detected on this page.</p>
        ) : (
          <ol className="divide-border-subtle divide-y">
            {ordered.map((issue, index) => (
              <li key={issue.id} className="flex items-center justify-between gap-3 py-2">
                <span className="flex min-w-0 items-center gap-3">
                  <span className="mono text-muted w-6 shrink-0 text-xs">{index + 1}</span>
                  <span className="text-foreground truncate text-sm">{issueTitle(issue)}</span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  <Badge
                    className={cn(
                      issue.dimension === 'aeo' ? 'text-accent-text' : 'text-info-text',
                    )}
                  >
                    {dimensionLabel(issue.dimension)}
                  </Badge>
                  <Badge variant="status" value={severityBadgeValue(issue.severity)}>
                    {severityLabel(issue.severity)}
                  </Badge>
                </span>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

function formatMeasuredMs(value: number | null): string {
  return value === null || value <= 0 ? PLACEHOLDER : `${Math.round(value)}ms`;
}

function formatBytes(bytes: number | null): string {
  if (bytes === null) return PLACEHOLDER;
  if (bytes < 1024) return `${bytes} B`;
  return `${Math.round((bytes / 1024) * 10) / 10} KB`;
}
