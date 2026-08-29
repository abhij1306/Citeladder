/**
 * Single source of truth for the demand-signal taxonomy.
 *
 * Signal grouping was previously written out three times (filter tabs, tab
 * counts, KPI cards), each free to drift from the others. Every grouping,
 * label, and metric read now derives from the maps here.
 */
import type { DemandSignal } from '@/lib/api/demand';

export type SignalType =
  | 'striking_distance'
  | 'query_cannibalization'
  | 'property_relative_ctr_gap'
  | 'high_impression_low_ctr'
  | 'emerging_query'
  | 'declining_query'
  | 'branded_query_performance';

export type FilterTab =
  'all' | 'striking_distance' | 'cannibalization' | 'ctr_gap' | 'trends' | 'branded';

/** Which signal types each filter tab admits. `all` admits everything. */
export const SIGNAL_GROUPS: Readonly<Record<Exclude<FilterTab, 'all'>, readonly SignalType[]>> = {
  striking_distance: ['striking_distance'],
  cannibalization: ['query_cannibalization'],
  ctr_gap: ['property_relative_ctr_gap', 'high_impression_low_ctr'],
  trends: ['emerging_query', 'declining_query'],
  branded: ['branded_query_performance'],
};

/** Tab order and labels for the filter bar. */
export const FILTER_TABS: readonly { tab: FilterTab; label: string }[] = [
  { tab: 'all', label: 'All Signals' },
  { tab: 'striking_distance', label: 'Striking Distance' },
  { tab: 'cannibalization', label: 'Cannibalization' },
  { tab: 'ctr_gap', label: 'CTR Gaps' },
  { tab: 'trends', label: 'Emerging / Declining' },
  { tab: 'branded', label: 'Branded Cohort' },
];

export function matchesTab(signal: DemandSignal, tab: FilterTab): boolean {
  if (tab === 'all') return true;
  return (SIGNAL_GROUPS[tab] as readonly string[]).includes(signal.signal_type);
}

export function countByTab(signals: readonly DemandSignal[], tab: FilterTab): number {
  return signals.reduce((total, signal) => total + (matchesTab(signal, tab) ? 1 : 0), 0);
}

/** Branded demand is navigational, so it is excluded from every gap rollup. */
export function isActionableGap(signal: DemandSignal): boolean {
  return signal.signal_type !== 'branded_query_performance';
}

/**
 * A metric value, or `null` when the backend did not observe one. Callers must
 * decide how an unobserved metric renders — this never invents a zero.
 */
export function numericMetric(signal: DemandSignal, key: string): number | null {
  const value = signal.metrics[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** The human-facing subject of a signal, tolerant of a non-string `target`. */
export function signalTarget(signal: DemandSignal): string {
  const target = signal.evidence.target;
  if (typeof target === 'string' && target.trim()) return target;
  return signal.topic_cluster || signal.page_url || '';
}

export function signalTargetKind(signal: DemandSignal): 'Page' | 'Query' {
  return signal.evidence.target_kind === 'page' ? 'Page' : 'Query';
}

/**
 * `signal.page_url` as a link target, or `null` when it is not a safe absolute
 * web URL.
 *
 * Stricter than the Markdown sanitiser in `lib/content/safe-url`: a demand
 * page URL is always an absolute address observed by the crawler, so relative
 * and `mailto:` values are rejected here rather than allowed. The value
 * ultimately originates from third-party Search Console data, so it is never
 * put in an `href` unvalidated.
 */
export function safePageUrl(pageUrl: string | null | undefined): string | null {
  if (!pageUrl) return null;
  const trimmed = pageUrl.trim();
  // Protocol-relative URLs must be rejected before parsing: `//evil.example`
  // inherits the app's scheme and would pass a post-parse protocol check.
  if (trimmed === '' || trimmed.startsWith('//')) return null;
  try {
    const { protocol } = new URL(trimmed);
    return protocol === 'http:' || protocol === 'https:' ? trimmed : null;
  } catch {
    return null;
  }
}

export type CompetingPage = { url: string; impressions: number; share: number };

/**
 * Competing URLs from cannibalization evidence, or `[]` when absent.
 *
 * `evidence` is `Record<string, unknown>`, so every field is validated: a page
 * missing `impressions`/`share` would otherwise reach `.toLocaleString()` and
 * `.toFixed()` on `undefined` at render time.
 */
export function competingPages(signal: DemandSignal): CompetingPage[] {
  const pages = signal.evidence.pages;
  if (!Array.isArray(pages)) return [];
  return pages.filter((page): page is CompetingPage => {
    if (typeof page !== 'object' || page === null) return false;
    const { url, impressions, share } = page as Partial<CompetingPage>;
    return (
      typeof url === 'string' &&
      typeof impressions === 'number' &&
      Number.isFinite(impressions) &&
      typeof share === 'number' &&
      Number.isFinite(share)
    );
  });
}

export type DetectorState = { state?: string; limitations?: string[] };

/**
 * `summary.detectors` is `unknown` on the wire — read it defensively.
 *
 * Each entry is normalised so consumers can rely on the shape: `limitations`
 * is always an array of strings (callers `.join()` it), and a non-string
 * `state` is dropped so it falls through to the caller's default.
 */
export function detectorStates(summary: Record<string, unknown>): Record<string, DetectorState> {
  const detectors = summary.detectors;
  if (!detectors || typeof detectors !== 'object' || Array.isArray(detectors)) return {};

  const normalised: Record<string, DetectorState> = {};
  for (const [key, value] of Object.entries(detectors as Record<string, unknown>)) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) continue;
    const { state, limitations } = value as { state?: unknown; limitations?: unknown };
    normalised[key] = {
      state: typeof state === 'string' ? state : undefined,
      limitations: Array.isArray(limitations)
        ? limitations.filter((item): item is string => typeof item === 'string')
        : [],
    };
  }
  return normalised;
}
