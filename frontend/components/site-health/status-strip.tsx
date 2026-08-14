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
  isAnalysisTerminal,
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

  if (phase === 'terminal') {
    // B1: a failed crawl names its reason (the API-projected failure summary /
    // humanized error_message, never a bare code) plus what to do next.
    const failure = crawl.status === 'failed' ? crawlFailureCopy(crawl) : null;
    return (
      <Alert tone={crawl.status === 'failed' ? 'danger' : 'info'}>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="run-status" value={crawlBadgeValue(crawl.status)}>
            {statusLabel(crawl.status)}
          </Badge>
          <span>
            {crawl.status === 'cancelled'
              ? 'This crawl was cancelled before it produced results.'
              : `${endSentence(failure?.reason ?? '')} ${failure?.guidance}`}
          </span>
        </div>
      </Alert>
    );
  }

  // phase === 'dashboard': quiet unless the run did not complete cleanly.
  const runNotice = dashboardRunNotice(crawl);
  if (!runNotice) return null;
  return (
    <Alert tone={runNotice.tone}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="run-status" value={runNotice.badge}>
          {statusLabel(crawl.status)}
        </Badge>
        <span>{runNotice.message}</span>
      </div>
    </Alert>
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
  const sampleMode = entitlement.access_mode === 'sample';
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
  // Fallbacks while the crawl is still running: `score_summary` is only
  // written when the crawl terminalizes, so derive the live view from server
  // counters instead of rendering 0s. `pages.length` is the last resort (a
  // bounded window, but better than nothing before the quota loads).
  const selected = summary?.selected_count ?? selectedTotal ?? pages.length;
  const completed = summary?.analyzed_count ?? crawl.analyzed_count;
  const failed = crawl.failed_count;
  // `completed`/`failed` use the server-aggregated crawl counters. `running`
  // is observed from the visible window (no server counter exists for it),
  // and `queued` is the arithmetic remainder — clamped at 0 so a transiently
  // stale mix of counters can never render a negative count. Until the
  // selected total is known, `Queued: 0` would misread as "nothing left to
  // do", so it renders the placeholder instead.
  const countsKnown = summary !== null || selectedTotal !== null;
  const running = pages.filter((p) => p.analysis_status === 'running').length;
  const queued = countsKnown ? Math.max(0, selected - completed - failed - running) : null;
  // A recrawl runs analysis of the monitored set WHILE re-discovery streams —
  // say so, instead of pretending only one sub-process exists. Never for a
  // sample crawl: Free copy must not imply continued full-site scanning.
  const discovering = !crawl.sample_mode && !isDiscoveryTerminal(crawl.discovery_status);
  // Once analysis terminalizes but the crawl is still active, the remaining
  // work is the link-check phase: every page shows "Completed" while the crawl
  // keeps running. That gap read as a hung crawl (and got cancelled), so the
  // phase now narrates itself instead of leaving the audit copy up.
  const linkChecking = !cancelPending && isAnalysisTerminal(crawl.analysis_status);
  let narration: string;
  if (cancelPending) {
    narration = 'Cancelling — finishing the page in flight and stopping';
  } else if (linkChecking) {
    narration = 'Pages analyzed — checking their links for broken destinations';
  } else if (discovering) {
    narration = 'Auditing monitored pages while discovery re-scans the site in the background';
  } else {
    narration = 'Auditing monitored pages for Web Fundamentals and AEO health issues';
  }

  return (
    <ProgressRow
      crawl={crawl}
      narration={narration}
      // Link checking and background re-discovery both leave the counters
      // still — the pulse is what distinguishes "working" from "stuck".
      active={linkChecking || discovering}
      counts={[
        { label: 'Total pages', value: countsKnown ? selected : null },
        { label: 'Completed', value: completed, className: 'text-run-completed' },
        { label: 'In progress', value: running, className: 'text-run-running' },
        { label: 'Queued', value: queued, className: 'text-muted' },
      ]}
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
