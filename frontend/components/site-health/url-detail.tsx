'use client';

import { useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, ChevronRight } from 'lucide-react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { CursorPager } from '@/components/ui/cursor-pager';
import { Card, CardContent } from '@/components/ui/card';
import { ScoreRing } from '@/components/ui/score-ring';
import { Skeleton } from '@/components/ui/skeleton';
import { Label, displayHeadingLgClasses } from '@/components/ui/typography';
import { ApiError } from '@/lib/api/errors';
import { queryKeys } from '@/lib/api/query-keys';
import { siteHealthMutations, siteHealthQueries } from '@/lib/api/site-health';
import type { DeliveryFacts, PageDetail, RerunPageResponse, SiteIssue } from '@/lib/api/types';
import { PageKindBadge } from '@/components/site-health/page-kind-badge';
import { ICONS } from '@/lib/icons';
import {
  pageKindLabel,
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
import { RERUN_MAX_PRE_ACTIVE_POLLS, RERUN_POLL_INTERVAL_MS } from '@/lib/config/site-health';

const HISTORY_LIMIT = 25;

/**
 * Per-URL Site Health detail (Slice 8, mockup 711).
 *
 * Renders URL metadata, overall/Web Fundamentals/AEO score rings, persisted delivery
 * facts (HTTP-level, not field CWV), the page's current issues ordered by
 * severity, and paginated crawl-bounded issue history. A "Re-audit this page"
 * action re-queues analysis (persisted server-side). Missing scores render `—`,
 * never a fabricated zero.
 */
/**
 * Search param the rerun flow appends when it navigates to the canonical
 * detail route of a *freshly minted* rerun crawl (`created_new_crawl`). On the
 * fresh mount it seeds `rerunPolling = true` so polling begins immediately
 * against the new crawl identity rather than waiting for a manual reload.
 */
const RERUN_SEARCH_PARAM = 'rerun';

export function UrlDetail({
  crawlId,
  siteUrlId,
}: Readonly<{ crawlId: string; siteUrlId: string }>) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  // A rerun that minted a NEW crawl navigates here with `?rerun=1`; start
  // polling on mount so the fresh run's queued/running progress is observed
  // without a manual reload.
  const [rerunPolling, setRerunPolling] = useState(
    () => searchParams.get(RERUN_SEARCH_PARAM) === '1',
  );
  // Guards against the immediately-post-mutation snapshot: right after the
  // rerun mutation resolves, the page-detail query cache still holds the
  // *previous* run's terminal `analysis_status` (e.g. `'completed'`) until a
  // refetch lands. Without this, the terminal-status effect below would see
  // that stale terminal snapshot and turn polling off before ever observing
  // the freshly-enqueued task's `'pending'`/`'running'` state. We only allow
  // polling to stop once we've actually observed a non-terminal snapshot
  // since the rerun was requested. A ref (not state): it is never rendered,
  // so updating it must not trigger a re-render.
  const hasObservedActiveRerunRef = useRef(false);
  const preActivePollCountRef = useRef(0);
  const [rerunError, setRerunError] = useState<string | null>(null);
  const detailQuery = useQuery({
    ...siteHealthQueries.page(crawlId, siteUrlId),
    // Poll while a rerun is in flight so the snapshot advances past the
    // queued/running state without a manual reload; stop once the analysis
    // reaches a terminal presentation status.
    refetchInterval: (query) => {
      if (!rerunPolling) return false;
      const status = query.state.data?.analysis_status;
      if (status === 'pending' || status === 'running') {
        hasObservedActiveRerunRef.current = true;
        preActivePollCountRef.current = 0;
        return RERUN_POLL_INTERVAL_MS;
      }
      if (status === undefined || !hasObservedActiveRerunRef.current) {
        if (preActivePollCountRef.current >= RERUN_MAX_PRE_ACTIVE_POLLS) return false;
        preActivePollCountRef.current += 1;
        return RERUN_POLL_INTERVAL_MS;
      }
      return false;
    },
  });
  const detail = detailQuery.data ?? null;

  if (detailQuery.isLoading) {
    return (
      <div className="grid gap-6">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (detailQuery.isError || !detail) {
    return <Alert tone="danger">Could not load this page. It may not exist in this crawl.</Alert>;
  }

  return (
    <div className="grid gap-6">
      <nav className="text-muted text-xs" aria-label="Breadcrumb">
        <Link href="/site-health" className="hover:text-accent">
          Site Health
        </Link>
        <span className="px-1.5" aria-hidden>
          /
        </span>
        <span className="text-secondary break-all">
          {pageDisplayTitle(detail.title, detail.display_url)}
        </span>
      </nav>

      <HeaderCard
        key={`header:${crawlId}:${siteUrlId}`}
        detail={detail}
        crawlId={crawlId}
        siteUrlId={siteUrlId}
        onRerunStart={() => setRerunError(null)}
        onRerunError={(error) => {
          if (error instanceof ApiError && error.status === 409) {
            setRerunError('This page is not in your monitored set — add it before re-auditing.');
          } else if (error instanceof ApiError && error.status === 403) {
            setRerunError('Re-auditing pages requires a Starter plan.');
          } else {
            setRerunError('Could not re-audit this page. Please try again.');
          }
        }}
        onRerunComplete={(result) => {
          // The backend may run the rerun in the SAME active crawl or mint a
          // fresh single-page crawl (when the source crawl was terminal). Poll
          // the identity the response points at — never the terminal source.
          if (result.crawl_id === crawlId && result.site_url_id === siteUrlId) {
            // Same crawl: poll in place. Reset the guard so the terminal-check
            // effect can't stop polling on the stale pre-rerun snapshot.
            hasObservedActiveRerunRef.current = false;
            preActivePollCountRef.current = 0;
            setRerunPolling(true);
            return;
          }
          // Fresh crawl: seed the new page's cache with the returned
          // non-terminal baseline so polling starts from a known state, then
          // navigate to the canonical detail route for the new identity with
          // `?rerun=1` so the remounted component begins polling immediately.
          queryClient.setQueryData<PageDetail>(
            queryKeys.siteHealth.page(result.crawl_id, result.site_url_id),
            (prev) =>
              prev
                ? { ...prev, crawl_id: result.crawl_id, analysis_status: result.analysis_status }
                : prev,
          );
          router.push(
            `/site-health/crawls/${result.crawl_id}/pages/${result.site_url_id}?${RERUN_SEARCH_PARAM}=1`,
          );
        }}
      />

      {rerunError ? <Alert tone="danger">{rerunError}</Alert> : null}

      <div className="grid gap-4 sm:grid-cols-3">
        <ScoreTile label="Web Fundamentals" value={detail.technical_score} />
        <ScoreTile label="AEO Health" value={detail.aeo_score} />
        <ScoreTile label="Combined" value={detail.overall_score} />
      </div>

      <DeliveryMetrics delivery={detail.delivery} />

      <IssuesList issues={detail.issues} />

      <IssueHistory
        key={`history:${crawlId}:${siteUrlId}`}
        crawlId={crawlId}
        siteUrlId={siteUrlId}
      />
    </div>
  );
}

function HeaderCard({
  detail,
  crawlId,
  siteUrlId,
  onRerunStart,
  onRerunError,
  onRerunComplete,
}: Readonly<{
  detail: PageDetail;
  crawlId: string;
  siteUrlId: string;
  onRerunStart: () => void;
  onRerunError: (error: unknown) => void;
  onRerunComplete: (result: RerunPageResponse) => void;
}>) {
  const queryClient = useQueryClient();
  const [reaudited, setReaudited] = useState(false);
  // The persisted classifier evidence behind `page_kind` ("why this type?"
  // disclosure); null for pages analyzed before evidence persistence or not
  // yet analyzed, in which case the toggle is not offered at all.
  const pageKindEvidence = readPageKindEvidence(detail.page_kind_evidence, detail.page_kind);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  // Null when the pack classifier never ran for this page: the whole Industry
  // Role row is then absent rather than showing an empty one.
  const rerun = useMutation({
    ...siteHealthMutations.rerunPage(),
    onSuccess: async (result) => {
      setReaudited(true);
      // When the rerun stays in the SAME crawl, invalidate its page query so
      // polling refetches the freshly-enqueued pending/running snapshot. When
      // it minted a NEW crawl, the parent navigates to the new identity, so
      // invalidating the source crawl's (now-terminal) query is unnecessary.
      if (result.crawl_id === crawlId && result.site_url_id === siteUrlId) {
        await queryClient.invalidateQueries({
          queryKey: queryKeys.siteHealth.page(crawlId, siteUrlId),
        });
      }
      onRerunComplete(result);
    },
    onError: onRerunError,
  });

  return (
    <Card>
      <CardContent className="grid gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          {/* `min-w-0` + `break-all`: a page with no <title> falls back to its
              URL, which is one unbreakable token — untreated it widened the
              header past the card and pushed Re-audit off screen. */}
          <div className="grid min-w-0 gap-1">
            <h1 className={cn(displayHeadingLgClasses, 'break-all')}>
              {pageDisplayTitle(detail.title, detail.display_url)}
            </h1>
          </div>
          <Button
            size="sm"
            onClick={() => {
              onRerunStart();
              rerun.mutate({ crawlId, siteUrlId });
            }}
            disabled={rerun.isPending}
          >
            {rerun.isPending
              ? 'Re-auditing…'
              : reaudited
                ? 'Re-audit queued'
                : 'Re-audit this page'}
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
 * The expanded "why this type?" disclosure (approved mockup
 * why-this-type-expanded): the classifier verdict facts, a highlighted
 * warning when the schema-suggested type conflicts with the final type, and
 * the ranked matched signals with their weights. Purely presentational —
 * all parsing/shaping lives in `readPageKindEvidence`.
 */
function PageKindEvidencePanel({
  evidence,
  finalPageKind,
}: Readonly<{ evidence: PageKindEvidenceView; finalPageKind: string | null }>) {
  const WarningIcon = ICONS.warning;
  return (
    <div id="page-kind-evidence">
      <div className="border-border-subtle bg-background-alt grid gap-3 rounded-lg border p-3">
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
          <span className="grid gap-0.5">
            <Label>Classified by</Label>
            <span className="mono text-foreground text-sm font-medium">
              {evidence.classifiedBy}
            </span>
          </span>
          <span className="grid gap-0.5">
            <Label>Confidence</Label>
            <span className="mono text-foreground text-sm font-medium">
              {evidence.confidence.toFixed(2)}{' '}
              <span className="text-muted font-medium">
                / {evidence.confidenceThreshold.toFixed(2)} threshold
              </span>
            </span>
          </span>
          <span className="grid gap-0.5">
            <Label>Schema suggests</Label>
            <span
              className={cn(
                'mono text-sm font-medium',
                evidence.schemaConflict ? 'text-warning-text' : 'text-foreground',
              )}
            >
              {evidence.schemaSuggestedType === null
                ? PLACEHOLDER
                : pageKindLabel(evidence.schemaSuggestedType)}
            </span>
          </span>
          <span className="grid gap-0.5">
            <Label>Signals matched</Label>
            <span className="mono text-foreground text-sm font-medium">
              {evidence.signals.length}
            </span>
          </span>
        </div>

        {evidence.otherReason !== null ? (
          <div
            role="note"
            className="border-border-subtle text-secondary rounded-sm border px-3 py-2 text-sm"
          >
            {evidence.otherReason === 'below_threshold'
              ? 'Signals matched but scored below the confidence threshold, so the page stayed unclassified.'
              : 'No classification signals matched this page.'}
          </div>
        ) : null}

        {evidence.alternatives.length > 0 ? (
          <div className="grid gap-1">
            <Label>Other candidates</Label>
            <div className="flex flex-wrap items-center gap-1.5">
              {evidence.alternatives.map((candidate) => (
                <span key={candidate.pageKind} className="flex items-center gap-1">
                  <Badge>{pageKindLabel(candidate.pageKind)}</Badge>
                  <span className="mono text-2xs text-muted tabular-nums">
                    {candidate.confidence.toFixed(2)}
                  </span>
                </span>
              ))}
            </div>
          </div>
        ) : null}

        {evidence.conflicts.length > 0 ? (
          <div className="grid gap-1">
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
          </div>
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

        {evidence.signals.length > 0 ? (
          <div className="grid">
            {evidence.signals.map((signal, index) => {
              const chosen = signal.signal === evidence.classifiedBy;
              return (
                <div
                  key={signal.signal}
                  className="border-border-subtle flex flex-wrap items-center gap-x-3 gap-y-1 border-b py-1.5 last:border-b-0"
                >
                  <span className="mono text-muted w-4.5 shrink-0 text-xs">{index + 1}</span>
                  <span
                    className={cn('mono text-sm', chosen ? 'text-foreground' : 'text-secondary')}
                  >
                    {signal.signal}
                    {chosen ? (
                      <span className="text-2xs text-accent-text ms-1.5 font-medium">chosen</span>
                    ) : null}
                  </span>
                  <span className="shrink-0">
                    <Badge>{pageKindLabel(signal.pageKind)}</Badge>
                  </span>
                  <span
                    className={cn(
                      'mono text-sm font-medium tabular-nums',
                      chosen ? 'text-foreground' : 'text-secondary',
                    )}
                  >
                    {signal.weight.toFixed(2)}
                  </span>
                  <span className="flex min-w-0 flex-1 items-center gap-3">
                    <span className="bg-border h-1 w-16 shrink-0 rounded-full">
                      <span
                        className="bg-accent block h-1 rounded-full opacity-60"
                        style={{
                          width: `${Math.min(100, Math.max(0, signal.weight * 100))}%`,
                        }}
                      />
                    </span>
                    <span className="mono text-muted truncate text-xs" title={signal.detail}>
                      {signal.detail}
                    </span>
                  </span>
                </div>
              );
            })}
          </div>
        ) : null}

        <div className="text-2xs text-muted flex flex-wrap items-center gap-x-4 gap-y-1">
          <span>
            Signals are evaluated in a fixed priority order; the highest-priority match sets the
            type.
          </span>
          <span className="mono ms-auto">{evidence.classifierVersion}</span>
        </div>
      </div>
    </div>
  );
}

function ScoreTile({ label, value }: Readonly<{ label: string; value: number | null }>) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-2 py-6">
        {value === null ? (
          <div className="mono border-border-subtle text-muted flex size-16 items-center justify-center rounded-full border text-base">
            {PLACEHOLDER}
          </div>
        ) : (
          <ScoreRing value={value} size={64} label={`${label}: ${Math.round(value)}`} />
        )}
        <Label>{label}</Label>
      </CardContent>
    </Card>
  );
}

/** Persisted HTTP delivery facts (mockup 711 "Delivery Metrics"). */
function DeliveryMetrics({ delivery }: Readonly<{ delivery: DeliveryFacts }>) {
  const items: Array<{ label: string; value: string }> = [
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
          <h2 className="text-foreground text-heading-sm">Delivery Metrics</h2>
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

/** Current issues on the page, ordered by severity (mockup 711 "All Issues"). */
function IssuesList({ issues }: Readonly<{ issues: SiteIssue[] }>) {
  const ordered = [...issues].sort((a, b) => severityRank(a.severity) - severityRank(b.severity));
  return (
    <Card>
      <CardContent className="grid gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-foreground text-heading-sm">All Issues ({issues.length})</h2>
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

/** Paginated, crawl-bounded per-URL issue history (newest first). */
function IssueHistory({ crawlId, siteUrlId }: Readonly<{ crawlId: string; siteUrlId: string }>) {
  const [cursorStack, setCursorStack] = useState<string[]>([]);
  const cursor = cursorStack.at(-1);
  const historyQuery = useQuery(
    siteHealthQueries.issueHistory(crawlId, siteUrlId, { cursor, limit: HISTORY_LIMIT }),
  );
  const rows = historyQuery.data?.items ?? [];
  const nextCursor = historyQuery.data?.next_cursor ?? null;
  const canPrev = cursorStack.length > 0;

  return (
    <Card>
      <CardContent className="grid gap-3">
        <h2 className="text-foreground text-heading-sm">Issue History</h2>
        {historyQuery.isError ? (
          <Alert tone="danger">Could not load issue history.</Alert>
        ) : historyQuery.isLoading ? (
          <div className="grid gap-2">
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-full" />
          </div>
        ) : rows.length === 0 ? (
          <p className="text-secondary text-sm">No prior issue records for this page.</p>
        ) : (
          <ul className="divide-border-subtle divide-y">
            {rows.map((row) => (
              <li key={row.id} className="flex items-center justify-between gap-3 py-2">
                <span className="flex min-w-0 flex-col">
                  <span className="text-foreground truncate text-sm">{issueTitle(row)}</span>
                  <span className="text-2xs text-muted font-mono">
                    {formatAudited(row.created_at)}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  <Badge
                    className={cn(row.dimension === 'aeo' ? 'text-accent-text' : 'text-info-text')}
                  >
                    {dimensionLabel(row.dimension)}
                  </Badge>
                  <Badge variant="status" value={severityBadgeValue(row.severity)}>
                    {severityLabel(row.severity)}
                  </Badge>
                </span>
              </li>
            ))}
          </ul>
        )}
        {rows.length > 0 ? (
          <div className="flex items-center justify-end gap-2">
            <CursorPager
              canPrev={canPrev}
              canNext={Boolean(nextCursor)}
              onPrev={() => setCursorStack((prev) => prev.slice(0, -1))}
              onNext={() =>
                nextCursor &&
                setCursorStack((prev) =>
                  // Idempotent under rapid clicks: the captured nextCursor may
                  // already be on the stack before the rerender lands.
                  prev.at(-1) === nextCursor ? prev : [...prev, nextCursor],
                )
              }
            />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

/**
 * A measured elapsed-time metric, or the placeholder (B6).
 *
 * `0` is not a real timing: the fetcher records whole milliseconds, so a zero
 * means the hop was never measured (a redirect/no-body hop, or a legacy row
 * persisted before the metric existed) — not a sub-millisecond response.
 * Rendering it as "0ms" advertises impossibly fast delivery. Byte counts do
 * NOT share this rule (`0 B` is a real body), so `formatBytes` keeps `0`.
 */
function formatMeasuredMs(value: number | null): string {
  if (value === null || value <= 0) return PLACEHOLDER;
  return `${Math.round(value)}ms`;
}

/** Human-readable byte size (KB) or the placeholder. */
function formatBytes(bytes: number | null): string {
  if (bytes === null) return PLACEHOLDER;
  if (bytes < 1024) return `${bytes} B`;
  return `${Math.round((bytes / 1024) * 10) / 10} KB`;
}
