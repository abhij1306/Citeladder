/**
 * Site Health lifecycle / status presentation helpers (Task 2) — PURE.
 *
 * Maps the crawl overall/discovery/analysis sub-states, per-page analysis
 * states, and the neutral count-disclosure rules onto display view-models the
 * screens render without embedding business logic. No transport, no React.
 *
 * These helpers branch on CAPABILITIES (`access_mode`, `count_disclosure`),
 * never on a plan name — there is no commercial vocabulary in Site Health.
 *
 * Key product rules encoded here:
 *   - discovery counts are PROVISIONAL until discovery terminalizes ("N pages
 *     discovered so far" vs "N pages discovered");
 *   - sample mode never renders a total placeholder or count-dependent copy —
 *     `total_url_count` is null and there is no "discovered so far";
 *   - error / blocked rows are explicit states, never a fabricated zero score;
 *   - missing / not-yet-analysed scores render the `—` placeholder.
 */
import type {
  CrawlAnalysisStatus,
  CrawlDiscoveryStatus,
  CrawlOverallStatus,
  PageAnalysisStatus,
  SiteCrawl,
  SiteHealthEntitlement,
} from '@/lib/api/types';
import type { RunStatusValue, StatusValue } from '@/components/ui/badge-variants';
import { titleCaseStatus } from '@/lib/utils';

/** The not-yet-analysed / not-applicable placeholder (matches visibility UI). */
export const PLACEHOLDER = '—';

/** Rows per cursor page across the Site Health inventory/pages lists. */
export const PAGE_LIMIT = 25;

/** Poll cadence for the Site Health screen's active-crawl queries. */
export const POLL_INTERVAL_MS = 4_000;

/** Overall crawl statuses that are terminal (stop polling). */
const TERMINAL_OVERALL: ReadonlySet<CrawlOverallStatus> = new Set<CrawlOverallStatus>([
  'completed',
  'partially_completed',
  'failed',
  'cancelled',
  'paused',
]);

/** Overall statuses at which a cooperative cancel is still meaningful. */
const CANCELABLE_OVERALL: ReadonlySet<CrawlOverallStatus> = new Set<CrawlOverallStatus>([
  'draft',
  'validating',
  'queued',
  'running',
]);

/** Discovery sub-states that are terminal. */
const TERMINAL_DISCOVERY: ReadonlySet<CrawlDiscoveryStatus> = new Set<CrawlDiscoveryStatus>([
  'completed',
  'sample_completed',
  'failed',
  'cancelled',
]);

/** Analysis sub-states that are terminal. */
const TERMINAL_ANALYSIS: ReadonlySet<CrawlAnalysisStatus> = new Set<CrawlAnalysisStatus>([
  'completed',
  'partially_completed',
  'failed',
  'cancelled',
]);

/** True while the crawl page should keep polling `GET /site-crawls/{id}`. */
export function shouldPollCrawl(crawl: Pick<SiteCrawl, 'status'>): boolean {
  return !TERMINAL_OVERALL.has(crawl.status);
}

/**
 * How long an active crawl may go without progressing before we treat it as
 * stalled: stop polling and say so, rather than spinning forever.
 *
 * The backend has its own backstop that force-terminalizes a crawl whose queue
 * has drained (`stalled_crawl_reconcile_seconds`), so this should be
 * unreachable in practice. It exists because the failure it guards against —
 * an active-forever crawl — used to pin every open tab to an endless 4s poll
 * of five queries, which is both the worst symptom for the user and the one
 * the client can unilaterally refuse to participate in. Comfortably above the
 * backend threshold so the server always gets to resolve it first.
 */
export const STALL_TIMEOUT_MS = 10 * 60_000;

/**
 * Poll cadence for an active crawl, backed off by how long it has been running.
 *
 * A flat 4s for a crawl's entire lifetime is right for the first minute and
 * wasteful for the twentieth: large crawls are the ones that both take longest
 * and cost the most per poll. SSE (`useCrawlEvents`) is what keeps a long crawl
 * feeling live, so the slower tick is only the safety net's cadence.
 *
 * Returns `false` once the crawl is terminal or has stalled — the value React
 * Query's `refetchInterval` expects for "stop".
 */
export function crawlPollInterval(
  crawl: Pick<SiteCrawl, 'status' | 'started_at' | 'created_at' | 'updated_at'>,
  now: number = Date.now(),
): number | false {
  if (!shouldPollCrawl(crawl)) return false;
  // Back off on how long the crawl has RUN, but stall on how long it has been
  // SILENT: `updated_at` moves on every counter/status write, so a large crawl
  // that is genuinely progressing never trips the stall cutoff no matter how
  // long it takes.
  const startedAt = crawl.started_at ?? crawl.created_at;
  const running = _sinceMs(startedAt, now);
  const silent = _sinceMs(crawl.updated_at ?? startedAt, now);
  if (silent === null || running === null) return POLL_INTERVAL_MS;
  if (silent >= STALL_TIMEOUT_MS) return false;
  if (running >= 5 * 60_000) return 30_000;
  if (running >= 60_000) return 10_000;
  return POLL_INTERVAL_MS;
}

/** Elapsed ms since an ISO timestamp; null when unusable (skew, unparseable). */
function _sinceMs(iso: string | null | undefined, now: number): number | null {
  if (!iso) return null;
  const elapsed = now - new Date(iso).getTime();
  return Number.isFinite(elapsed) && elapsed >= 0 ? elapsed : null;
}

/**
 * True when an ACTIVE crawl has gone quiet for longer than `STALL_TIMEOUT_MS`
 * and polling has been given up. The screen renders an explicit stalled notice
 * instead of an indefinite progress state.
 */
export function isCrawlStalled(
  crawl: Pick<SiteCrawl, 'status' | 'started_at' | 'created_at' | 'updated_at'> | null,
  now: number = Date.now(),
): boolean {
  if (!crawl || !shouldPollCrawl(crawl)) return false;
  return crawlPollInterval(crawl, now) === false;
}

/** True when the crawl can still be cancelled cooperatively. */
export function isCrawlCancelable(status: CrawlOverallStatus): boolean {
  return CANCELABLE_OVERALL.has(status);
}

export function isDiscoveryTerminal(status: CrawlDiscoveryStatus): boolean {
  return TERMINAL_DISCOVERY.has(status);
}

export function isAnalysisTerminal(status: CrawlAnalysisStatus): boolean {
  return TERMINAL_ANALYSIS.has(status);
}

/**
 * True while discovery counts are provisional (still running). A `sample_mode`
 * crawl is NEVER provisional — it never implies continued full-site scanning,
 * so it must never be checked into shared background-scanning copy without
 * this shared helper enforcing the rule itself (not left to each caller).
 */
export function isDiscoveryProvisional(
  crawl: Pick<SiteCrawl, 'sample_mode' | 'discovery_status' | 'inventory_complete'>,
): boolean {
  if (crawl.sample_mode) return false;
  return !crawl.inventory_complete && !TERMINAL_DISCOVERY.has(crawl.discovery_status);
}

/** True when the crawl is a server-selected sample crawl. */
export function isSampleMode(crawl: Pick<SiteCrawl, 'sample_mode'>): boolean {
  return crawl.sample_mode;
}

/**
 * Discovery-progress copy. Sample mode NEVER renders a total or "so far"
 * language (no count side channel); selection mode uses provisional
 * "discovered so far" until discovery terminalizes, then the settled
 * "discovered".
 */
export function discoveryProgressLabel(
  crawl: Pick<
    SiteCrawl,
    'sample_mode' | 'discovery_status' | 'inventory_complete' | 'visible_url_count'
  >,
): string {
  const n = crawl.visible_url_count;
  if (crawl.sample_mode) {
    return `${n} sample ${pluralize(n, 'page')}`;
  }
  if (isDiscoveryProvisional(crawl)) {
    return `${n} ${pluralize(n, 'page')} discovered so far`;
  }
  return `${n} ${pluralize(n, 'page')} discovered`;
}

/**
 * Whether a discovered/total count may be shown at all. `count_disclosure` is
 * the neutral capability that governs it — an account without it sees no total
 * at all: the value is null on the wire and no placeholder is rendered.
 */
export function canShowDiscoveredTotal(
  entitlement: Pick<SiteHealthEntitlement, 'count_disclosure'>,
  crawl: Pick<SiteCrawl, 'sample_mode' | 'total_url_count'>,
): boolean {
  return entitlement.count_disclosure && !crawl.sample_mode && crawl.total_url_count !== null;
}

/**
 * Which phase of the Site Health flow to render.
 *
 * RESOLVED SERVER-SIDE (backend/app/domain/site_health/phase.py) and read off
 * the dashboard projection. `'resolving'` is the one value the server never
 * sends: it means the dashboard request itself has not landed yet.
 */
export type SiteHealthPhase =
  'resolving' | 'empty' | 'discovering' | 'selection' | 'analyzing' | 'dashboard' | 'terminal';

/**
 * Fingerprint of everything on a crawl that means "progress happened".
 *
 * The screen polls ONE query (the dashboard). Every other crawl-derived list —
 * pages, inventory, issues — refreshes when this value changes rather than
 * owning a timer of its own: five independent 4s timers over the same crawl
 * resolve out of order, so panels rendered state from different moments (counts
 * ticking backwards, a score appearing then vanishing). `updated_at` alone
 * would nearly always suffice; the counters and sub-states are included so a
 * missed timestamp write cannot freeze the whole screen.
 */
export function crawlProgressVersion(
  crawl: Pick<
    SiteCrawl,
    | 'status'
    | 'discovery_status'
    | 'analysis_status'
    | 'visible_url_count'
    | 'analyzed_count'
    | 'failed_count'
    | 'updated_at'
  >,
): string {
  return [
    crawl.status,
    crawl.discovery_status,
    crawl.analysis_status,
    crawl.visible_url_count,
    crawl.analyzed_count,
    crawl.failed_count,
    crawl.updated_at ?? '',
  ].join('|');
}

/**
 * Which content the always-mounted inventory section renders for a phase. The
 * canonical Site Health screen never swaps whole panels — the layout (scores +
 * status row + inventory) stays mounted and only this mode changes:
 *   - 'discovering': read-only inventory rows streaming in;
 *   - 'selectable':  monitored-set staging (checkboxes + commit);
 *   - 'scored':      the tabbed (monitored/all/errors) page browser — used
 *                    DURING analysis and after: the same table, rows advance
 *                    queued → running → completed and scores fill in place;
 *   - 'none':        empty/terminal — nothing to list yet.
 */
export type InventoryMode = 'none' | 'discovering' | 'selectable' | 'scored';

export function inventoryModeForPhase(
  phase: SiteHealthPhase,
  crawl?: Pick<SiteCrawl, 'status'> | null,
): InventoryMode {
  switch (phase) {
    case 'discovering':
      return 'discovering';
    case 'selection':
      return 'selectable';
    case 'analyzing':
    case 'dashboard':
      // ONE table for the whole audit lifecycle: the analyzing phase renders
      // the same tabbed browser as the finished dashboard, so finishing a run
      // changes NOTHING structurally — statuses and scores update in place.
      return 'scored';
    case 'terminal':
      // B3: a FAILED crawl's terminal view keeps the tabbed page browser so
      // the Errors & Blocked tab stays reachable — it renders the root-failure
      // block (root_errors) even though no page rows exist. Any other
      // terminal shape (cancelled-with-nothing) lists nothing.
      return crawl?.status === 'failed' ? 'scored' : 'none';
    default:
      // 'resolving' | 'empty'
      return 'none';
  }
}

/**
 * Reason + what-to-do copy for a failed crawl (SH-2/SH-5 — B1), shared by the
 * terminal card and the dashboard run notice. The reason prefers the
 * API-projected `failure_summary.message` (humanized by the worker from the
 * terminal fetch evidence), falls back to the crawl row's `error_message`,
 * then to a neutral sentence — never a bare machine code.
 */
export type CrawlFailureCopy = { reason: string; guidance: string };

/** What-to-do next per stable failure code (default: plain re-crawl). */
function failureGuidanceFor(code: string | undefined): string {
  switch (code) {
    case 'dns_resolution_failed':
      return 'Check that the domain is spelled correctly and publicly reachable, then re-crawl.';
    case 'connection_failed':
    case 'timeout':
      return 'The site may be down or blocking automated traffic — re-crawl to try again.';
    case 'robots_denied':
      return "Allow the crawler in the site's robots.txt, then re-crawl.";
    case 'robots_unavailable':
      return 'This is usually temporary — re-crawl to try again.';
    case 'bot_blocked':
      return 'Allowlist the crawler with the site’s bot protection, then re-crawl.';
    case 'http_4xx':
      return 'Check that the start URL is correct and publicly reachable, then re-crawl.';
    case 'http_5xx':
      return 'The site is having server trouble — this is often temporary; re-crawl to try again.';
    case 'ssrf_blocked':
      return 'Choose a publicly reachable start URL, then re-crawl.';
    default:
      return 'Re-crawl to try again.';
  }
}

export function crawlFailureCopy(
  crawl: Pick<SiteCrawl, 'error_message' | 'failure_summary'>,
): CrawlFailureCopy {
  const reason =
    crawl.failure_summary?.message ||
    crawl.error_message ||
    'This crawl failed before it produced results.';
  return { reason, guidance: failureGuidanceFor(crawl.failure_summary?.code) };
}

/**
 * Failure reasons arrive WITHOUT terminal punctuation (the worker's humanized
 * sentences and legacy `error_message` rows alike); renderers join reason +
 * guidance as consecutive sentences, so normalize the join once here.
 */
export function endSentence(text: string): string {
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

/**
 * Dashboard run-outcome notice for a crawl whose results are shown but whose run
 * did NOT complete cleanly. Returns `null` for a completed crawl (no notice),
 * otherwise a text-labelled badge value + tone + message so the dashboard can
 * explicitly say "Cancelled" / "Partial" (never color-only) while still showing
 * the scores/inventory that already landed. Recrawl is offered by the header.
 */
export type DashboardRunNotice = {
  badge: RunStatusValue;
  tone: 'info' | 'warning';
  message: string;
} | null;

export function dashboardRunNotice(
  crawl: Pick<SiteCrawl, 'status' | 'analyzed_count' | 'error_message' | 'failure_summary'>,
): DashboardRunNotice {
  switch (crawl.status) {
    case 'cancelled':
      return {
        badge: 'cancelled',
        tone: 'info',
        message:
          'This run was cancelled — showing the pages analyzed so far. Re-crawl to complete the analysis.',
      };
    case 'partially_completed':
      return {
        badge: 'partial',
        tone: 'warning',
        message:
          'Some pages could not be analyzed — showing partial results. Re-crawl to retry the remaining pages.',
      };
    case 'failed': {
      const { reason, guidance } = crawlFailureCopy(crawl);
      // SH-2: with zero pages analyzed there is no "so far" to show — lead
      // with the failure reason instead of promising partial results.
      const headline =
        crawl.analyzed_count === 0
          ? 'The run failed before any page was analyzed.'
          : 'The run failed before finishing — showing the pages analyzed so far.';
      return {
        badge: 'failed',
        tone: 'warning',
        message: `${headline} ${endSentence(reason)} ${guidance}`,
      };
    }
    default:
      return null;
  }
}

/** Map an overall crawl status onto a run-status badge value. */
export function crawlBadgeValue(status: CrawlOverallStatus): RunStatusValue {
  switch (status) {
    case 'validating':
      return 'queued';
    case 'partially_completed':
      return 'partial';
    default:
      return status;
  }
}

/** Map a per-page analysis status onto a status-badge value. */
export function pageStatusBadgeValue(status: PageAnalysisStatus): StatusValue {
  switch (status) {
    case 'completed':
      return 'success';
    case 'partially_completed':
      return 'warning';
    case 'failed':
    case 'error':
    case 'blocked':
    case 'cancelled':
      return 'danger';
    default:
      // not_selected / pending / running
      return 'info';
  }
}

/** True when a page row is an explicit error/blocked state (not a zero score). */
export function isErrorRow(status: PageAnalysisStatus): boolean {
  return (
    status === 'failed' || status === 'error' || status === 'blocked' || status === 'cancelled'
  );
}

/** Human-readable label for any snake_case lifecycle token. */
export function statusLabel(status: string): string {
  return titleCaseStatus(status);
}

/**
 * Format a 0–100 score for display. Null (not yet analysed) and NaN render the
 * `—` placeholder — an error/blocked row is NEVER shown as 0.
 */
export function formatScore(score: number | null): string {
  if (score === null || Number.isNaN(score)) return PLACEHOLDER;
  return `${Math.round(score * 10) / 10}`;
}

/**
 * The label for a page row: its `<title>`, or the URL's last path segment.
 *
 * Repeating the whole URL as the title (the previous fallback) gave the row two
 * identical lines and let one long query string dominate the table. The last
 * segment is the part that actually distinguishes one page from its siblings,
 * so an untitled page reads as `/boys-shorts-aged-8-16` above its full URL.
 * The site root — and any URL we cannot parse — keeps the display URL, which is
 * the only meaningful thing left to say about it.
 */
export function pageDisplayTitle(title: string | null, displayUrl: string): string {
  const trimmed = title?.trim();
  if (trimmed) return trimmed;
  let pathname: string;
  try {
    ({ pathname } = new URL(displayUrl));
  } catch {
    return displayUrl;
  }
  // Query strings and fragments are already excluded by `pathname`; a trailing
  // slash would otherwise yield an empty final segment.
  const segments = pathname.split('/').filter(Boolean);
  const last = segments.at(-1);
  return last ? `/${last}` : displayUrl;
}

/** Format a nullable issue count; null (unanalysed) renders the placeholder. */
export function formatIssueCount(count: number | null): string {
  if (count === null) return PLACEHOLDER;
  return `${count}`;
}

/** Short, stable date/time label for a timestamp (or the placeholder). */
export function formatAudited(timestamp: string | null): string {
  if (!timestamp) return PLACEHOLDER;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function pluralize(n: number, word: string): string {
  return n === 1 ? word : `${word}s`;
}
