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
 *   - missing / not-yet-analysed scores render an explicit not-measured label.
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
import { availabilityLabel } from '@/lib/format';
import { titleCaseStatus } from '@/lib/utils';

/** The not-yet-analysed / not-applicable placeholder (matches visibility UI). */
export const PLACEHOLDER = availabilityLabel('not_measured');

/** Rows per cursor page across the Site Health inventory/pages lists. */
export const PAGE_LIMIT = 10;

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
 * Kept for callers that schedule age-based polling. Stalled classification is
 * backend-owned and never inferred from elapsed client time.
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
 * Returns `false` once the crawl is terminal — the value React Query's
 * `refetchInterval` expects for "stop".
 */
export function crawlPollInterval(
  crawl: Pick<SiteCrawl, 'status' | 'started_at' | 'created_at' | 'updated_at'>,
  now: number = Date.now(),
): number | false {
  if (!shouldPollCrawl(crawl)) return false;
  // Back off on how long the crawl has run. The backend activity projection
  // owns waiting/stalled semantics from leases and durable queue evidence.
  const startedAt = crawl.started_at ?? crawl.created_at;
  const running = _sinceMs(startedAt, now);
  if (running === null) return POLL_INTERVAL_MS;
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
 * True only when the backend reports expired-lease evidence for an active
 * crawl. Elapsed client time is deliberately not an input.
 */
export function isCrawlStalled(
  crawl: Pick<SiteCrawl, 'status' | 'counters'> | null,
  _now: number = Date.now(),
): boolean {
  if (!crawl || !shouldPollCrawl(crawl)) return false;
  return crawl.counters.activity.state === 'stalled';
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
 * language (no count side channel); full mode uses provisional
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
  'resolving' | 'empty' | 'discovering' | 'analyzing' | 'dashboard' | 'terminal';

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
 *   - 'scored':      the tabbed (monitored/all/errors) page browser — used
 *                    DURING analysis and after: the same table, rows advance
 *                    queued → running → completed and scores fill in place;
 *   - 'none':        empty/terminal — nothing to list yet.
 */
export type InventoryMode = 'none' | 'discovering' | 'scored';

export function inventoryModeForPhase(
  phase: SiteHealthPhase,
  crawl?: Pick<SiteCrawl, 'status'> | null,
): InventoryMode {
  switch (phase) {
    case 'discovering':
      return 'discovering';
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
 * Failure reasons arrive WITHOUT terminal punctuation (the worker's humanized
 * sentences and legacy `error_message` rows alike); renderers join reason +
 * guidance as consecutive sentences, so normalize the join once here.
 */
export function endSentence(text: string): string {
  return /[.!?]$/.test(text) ? text : `${text}.`;
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
 * `Not measured` placeholder — an error/blocked row is NEVER shown as 0.
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

// Run-outcome copy (failure reasons, partial reasons, the dashboard notice)
// lives in its own module. It is re-exported here because every caller has
// always reached it through `status`.
export {
  crawlFailureCopy,
  dashboardRunNotice,
  partialCrawlMessage,
  type CrawlFailureCopy,
  type DashboardRunNotice,
} from './run-notice';
