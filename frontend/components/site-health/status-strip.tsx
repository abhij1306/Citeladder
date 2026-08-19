'use client';

import type { ReactNode } from 'react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { AccentEyebrow } from '@/components/ui/eyebrow';
import { Label, Metric, displayHeadingLgClasses } from '@/components/ui/typography';
import type { PageSummary, SiteCrawl, SiteHealthEntitlement } from '@/lib/api/types';
import { cn } from '@/lib/utils';
import {
  PLACEHOLDER,
  canShowDiscoveredTotal,
  crawlBadgeValue,
  crawlFailureCopy,
  dashboardRunNotice,
  discoveryProgressLabel,
  endSentence,
  isDiscoveryProvisional,
  isDiscoveryTerminal,
  statusLabel,
  type SiteHealthPhase,
} from '@/lib/site-health/status';

/**
 * Always-mounted status row of the canonical Site Health screen.
 *
 * ONE compact row (badge + narration + inline counters) that narrates the
 * whole lifecycle in place below the score cards — discovery counts while
 * discovering, audit progress while analyzing, and the run-outcome notice
 * (`dashboardRunNotice`) for a run that did not complete cleanly. The row
 * changes CONTENT, never the screen: no phase mounts or unmounts the region,
 * and progress is never a separate panel that pushes the results around.
 * Free redaction rules apply — sample crawls never imply a hidden total.
 */
export function StatusStrip({
  crawl,
  phase,
  entitlement,
  cancelPending,
  startPending,
  pages,
  selectedTotal,
  selectedError,
}: Readonly<{
  crawl: SiteCrawl | null;
  phase: SiteHealthPhase;
  entitlement: SiteHealthEntitlement;
  cancelPending: boolean;
  /** A fresh crawl create is in flight — freeze current content behind a notice. */
  startPending: boolean;
  /** Bounded monitored-page window (observed "running" rows only, never totals). */
  pages: PageSummary[];
  /** This project's active monitored count; null until loaded. */
  selectedTotal: number | null;
  /** True when the monitored-count fetch failed (counts fall back, noted here). */
  selectedError: boolean;
}>) {
  // The wrapper (and its test id) stays mounted in every phase — only the
  // CONTENT below changes. The screen regression tests assert this stability.
  return (
    <div className="grid gap-2 empty:hidden" data-testid="status-strip">
      <StripContent
        crawl={crawl}
        phase={phase}
        entitlement={entitlement}
        cancelPending={cancelPending}
        startPending={startPending}
        pages={pages}
        selectedTotal={selectedTotal}
        selectedError={selectedError}
      />
    </div>
  );
}

function StripContent({
  crawl,
  phase,
  entitlement,
  cancelPending,
  startPending,
  pages,
  selectedTotal,
  selectedError,
}: Readonly<{
  crawl: SiteCrawl | null;
  phase: SiteHealthPhase;
  entitlement: SiteHealthEntitlement;
  cancelPending: boolean;
  startPending: boolean;
  pages: PageSummary[];
  selectedTotal: number | null;
  selectedError: boolean;
}>) {
  if (startPending) {
    return (
      <Alert tone="info">
        {crawl
          ? 'Starting a fresh crawl — current results stay visible until the new run completes.'
          : 'Starting crawl — pages will appear below as they are found.'}
      </Alert>
    );
  }

  // The phase inputs have not all settled: say nothing rather than narrate a
  // state that is about to be corrected. (The screen holds its skeleton for
  // this beat, so it is not normally reached from there.)
  if (phase === 'resolving') return null;

  if (!crawl || phase === 'empty') {
    // Direct component callers retain an empty-state fallback. The canonical
    // layout owns the actionable first-crawl placeholder.
    return (
      <Card>
        <CardContent className="grid justify-items-center gap-3 py-10 text-center">
          <AccentEyebrow>Site health</AccentEyebrow>
          <h2 className={displayHeadingLgClasses}>No crawl yet</h2>
          <p className="text-secondary max-w-md text-sm">
            Discover and analyze your site&apos;s pages for AI search optimization. Start a crawl to
            see your pages, scores, and issues here — this screen updates in place as the crawl
            progresses.
          </p>
        </CardContent>
      </Card>
    );
  }

  if (phase === 'discovering') {
    return <DiscoveryStrip crawl={crawl} entitlement={entitlement} cancelPending={cancelPending} />;
  }

  if (phase === 'analyzing') {
    return (
      <AnalysisStrip
        crawl={crawl}
        cancelPending={cancelPending}
        pages={pages}
        selectedTotal={selectedTotal}
        selectedError={selectedError}
      />
    );
  }

  if (phase === 'terminal') return <TerminalNotice crawl={crawl} />;
  return <DashboardNotice crawl={crawl} />;
}

function TerminalNotice({ crawl }: Readonly<{ crawl: SiteCrawl }>) {
  const failure = crawl.status === 'failed' ? crawlFailureCopy(crawl) : null;
  const message =
    crawl.status === 'cancelled'
      ? 'This crawl was cancelled before it produced results.'
      : crawl.status === 'paused'
        ? 'This crawl is paused and has no completed score yet. Run a new crawl to try again.'
        : failure
          ? [endSentence(failure.reason), failure.guidance].filter(Boolean).join(' ')
          : 'This crawl ended before it produced results. Run a new crawl to try again.';
  return (
    <Alert tone={failure ? 'danger' : 'info'}>
      <RunNotice crawl={crawl} message={message} />
    </Alert>
  );
}

function DashboardNotice({ crawl }: Readonly<{ crawl: SiteCrawl }>) {
  const notice = dashboardRunNotice(crawl);
  return notice ? (
    <Alert tone={notice.tone}>
      <RunNotice crawl={crawl} message={notice.message} badge={notice.badge} />
    </Alert>
  ) : null;
}

function RunNotice({
  crawl,
  message,
  badge = crawlBadgeValue(crawl.status),
}: Readonly<{ crawl: SiteCrawl; message: string; badge?: ReturnType<typeof crawlBadgeValue> }>) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant="run-status" value={badge}>
        {statusLabel(crawl.status)}
      </Badge>
      <span>{message}</span>
    </div>
  );
}

/**
 * The shared one-row shell: status badge + live narration on the left, the
 * inline counters on the right, wrapping on narrow screens. Extra content
 * (Free upsell, count-fetch warnings) stacks compactly underneath.
 */
function ProgressRow({
  crawl,
  narration,
  counts,
  active,
  children,
}: Readonly<{
  crawl: SiteCrawl;
  narration: string;
  counts: ReadonlyArray<{ label: string; value: number | null; className?: string }>;
  /** Show the live pulse — work is ongoing but not reflected in the counters. */
  active?: boolean;
  children?: ReactNode;
}>) {
  return (
    <Card>
      <CardContent className="grid gap-3 py-3">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <div className="flex min-w-0 items-center gap-3">
            <Badge variant="run-status" value={crawlBadgeValue(crawl.status)}>
              {statusLabel(crawl.status)}
            </Badge>
            <span className="text-secondary flex min-w-0 items-center gap-2 text-sm">
              {active ? (
                <span
                  aria-hidden
                  data-testid="activity-pulse"
                  className="activity-dot bg-run-running size-1.5 shrink-0"
                />
              ) : null}
              {/* The live region is the TEXT, not the row: announcing the whole
                  row would re-read every counter on each poll. */}
              <span className="truncate" aria-live="polite">
                {narration}
              </span>
            </span>
          </div>
          <dl className="ml-auto flex flex-wrap items-baseline gap-x-6 gap-y-1">
            {counts.map((count) => (
              <div key={count.label} className="flex items-baseline gap-1.5">
                <Label>{count.label}</Label>
                <Metric className={cn('text-sm', count.className)}>
                  {count.value ?? PLACEHOLDER}
                </Metric>
              </div>
            ))}
          </dl>
        </div>
        {children}
      </CardContent>
    </Card>
  );
}

function DiscoveryStrip({
  crawl,
  entitlement,
  cancelPending,
}: Readonly<{
  crawl: SiteCrawl;
  entitlement: SiteHealthEntitlement;
  cancelPending: boolean;
}>) {
  const provisional = isDiscoveryProvisional(crawl);
  const showTotal = canShowDiscoveredTotal(entitlement, crawl);
  // Neutral capability, not a plan name: `sample` means the server picks a
  // bounded sample; full mode uses the crawl's automatic admission allowance.
  const sampleMode = crawl.sample_mode;
  let narration: string;
  if (cancelPending) {
    narration = 'Stopping crawl — finishing the page in flight';
  } else if (provisional) {
    narration = `${discoveryProgressLabel(crawl)} — scanning continues in the background`;
  } else {
    narration = discoveryProgressLabel(crawl);
  }

  const counts: Array<{ label: string; value: number | null }> = [
    { label: sampleMode ? 'Sample URLs' : 'URLs found', value: crawl.visible_url_count },
  ];
  if (showTotal && crawl.total_url_count !== null) {
    counts.push({ label: 'Total discovered', value: crawl.total_url_count });
  }

  return (
    <ProgressRow crawl={crawl} narration={narration} counts={counts} active={!cancelPending}>
      {sampleMode ? (
        <p className="text-muted text-sm">
          We&apos;ll automatically analyze a {entitlement.sample_url_limit}-page sample of your
          site. Choosing which pages to monitor needs a monitored-URL allowance.
        </p>
      ) : null}
    </ProgressRow>
  );
}

function AnalysisStrip({
  crawl,
  cancelPending,
  pages,
  selectedTotal,
  selectedError,
}: Readonly<{
  crawl: SiteCrawl;
  cancelPending: boolean;
  pages: PageSummary[];
  selectedTotal: number | null;
  selectedError: boolean;
}>) {
  const summary = crawl.score_summary;
  const selected =
    crawl.counters.selected || summary?.selected_count || selectedTotal || pages.length;
  const narration = analysisNarration(crawl, cancelPending);

  return (
    <ProgressRow
      crawl={crawl}
      narration={narration}
      // Background re-discovery can leave the counters still; the pulse is
      // what distinguishes "working" from "stuck".
      active={!cancelPending && crawl.counters.activity.state !== 'stalled'}
      counts={analysisCounts(crawl, selected)}
    >
      {selectedError ? (
        <Alert tone="warning">
          Could not load the monitored-page count — progress totals may be approximate until it
          refreshes.
        </Alert>
      ) : null}
    </ProgressRow>
  );
}

type ProgressCount = { label: string; value: number | null; className?: string };

function analysisNarration(crawl: SiteCrawl, cancelPending: boolean): string {
  if (cancelPending) return 'Cancelling — finishing the page in flight and stopping';
  if (crawl.counters.activity.state === 'waiting') {
    return crawl.counters.activity.reason === 'host_gate'
      ? 'Waiting for the site host gate while the worker lease stays healthy'
      : 'Waiting for the next persisted retry window';
  }
  if (crawl.counters.activity.state === 'stalled')
    return 'Worker lease expired — recovery is pending';
  return !crawl.sample_mode && !isDiscoveryTerminal(crawl.discovery_status)
    ? 'Auditing monitored pages while discovery re-scans the site in the background'
    : 'Auditing monitored pages for Web Fundamentals and AEO health issues';
}

function analysisCounts(crawl: SiteCrawl, selected: number): ProgressCount[] {
  const { counters } = crawl;
  const fixed: ProgressCount[] = [
    { label: 'Total pages', value: selected },
    { label: 'Completed', value: counters.analyzed, className: 'text-run-completed' },
    { label: 'In progress', value: counters.running, className: 'text-run-running' },
    { label: 'Queued', value: counters.queued, className: 'text-muted' },
  ];
  const robots = counters.failure_breakdown.robots_denied;
  if (robots > 0) {
    fixed.push({ label: 'Blocked by robots.txt', value: robots, className: 'text-run-blocked' });
  }
  return [
    ...fixed,
    ...(['http_4xx', 'http_5xx', 'timeout'] as const)
      .filter((code) => counters.failure_breakdown[code] > 0)
      .map((code) => ({
        label: code === 'timeout' ? 'Timeouts' : code.replace('_', ' ').toUpperCase(),
        value: counters.failure_breakdown[code],
        className: 'text-run-error',
      })),
  ];
}
