/**
 * Site Health run-outcome copy — PURE.
 *
 * Why a crawl did not finish cleanly, in the reader's language: the failure
 * reason plus what to do about it, and the notice the dashboard shows above
 * results that did land.
 *
 * The rule that shapes the partial copy: a crawl that could not FETCH some URLs
 * and one whose ANALYSES fell short are different outcomes, and only the second
 * is a problem with the audit. Every real site has some dead, blocked, or
 * non-page links, so one message blaming analysis fired on effectively every
 * crawl. The backend names the reason; this module never infers it.
 */
import type { RunStatusValue } from '@/components/ui/badge-variants';
import type { SiteCrawl } from '@/lib/api/types';

import { endSentence } from './status';

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

/**
 * What a `partially_completed` crawl actually means, from the backend's own
 * reason code.
 *
 * These are different outcomes and only one of them is a problem with the
 * audit. On any real site a handful of discovered links are dead, blocked, or
 * not web pages at all — that is a normal crawl, not a failed analysis, and
 * "re-crawl to retry" will not change it. The screen used to show the analysis
 * sentence for every partial crawl, so effectively every crawl looked broken.
 */
const PARTIAL_MESSAGES: Record<string, string> = {
  discovery_incomplete:
    'Some links could not be fetched — they were dead, blocked, or not web pages. Every page that was fetched has been analyzed.',
  analysis_incomplete:
    'Some pages could not be analyzed — showing partial results. Re-crawl to retry the remaining pages.',
  discovery_and_analysis_incomplete:
    'Some links could not be fetched, and some fetched pages could not be analyzed. Re-crawl to retry the pages that failed analysis.',
};

const PARTIAL_FALLBACK =
  'This crawl finished with partial results — showing everything it did analyze.';

export function partialCrawlMessage(partialReason: string): string {
  return PARTIAL_MESSAGES[partialReason] ?? PARTIAL_FALLBACK;
}

export function dashboardRunNotice(
  crawl: Pick<
    SiteCrawl,
    'status' | 'analyzed_count' | 'error_message' | 'failure_summary' | 'partial_reason'
  >,
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
        // A discovery-only shortfall is an observation, not a warning: nothing
        // about the analysis went wrong and there is nothing to retry.
        tone: crawl.partial_reason === 'discovery_incomplete' ? 'info' : 'warning',
        message: partialCrawlMessage(crawl.partial_reason),
      };
    case 'paused':
      return {
        badge: 'paused',
        tone: 'info',
        message:
          'This run is paused — showing the pages analyzed so far. Run a new crawl to refresh the results.',
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
