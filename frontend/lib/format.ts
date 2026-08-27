/**
 * Shared display-format vocabulary (F5–F9) — ONE owner (invariant 2) for the
 * date / count / URL / snapshot-granularity formatters the Traffic,
 * AI Referrals, and Settings→Integrations surfaces all render with.
 *
 * The domain modules (`lib/traffic/traffic`, `lib/ai-referrals/options`,
 * `lib/ai-referrals/series`) re-export these under their local names so
 * domain import sites stay local; new code should import from here.
 *
 * Everything is pure and framework-free; explicit locales + UTC keep SSR/CSR
 * output identical. Unparseable input passes through untouched — never a
 * fabricated value (invariant 9).
 */
import type { z } from 'zod';

import type { snapshotGranularitySchema } from '@/lib/api/schemas';

/** Snapshot bucket granularity — mirrors the backend contract vocabulary. */
type BucketGranularity = z.infer<typeof snapshotGranularitySchema>;

export type DataAvailabilityState =
  'not_measured' | 'not_run' | 'not_set' | 'unavailable' | 'not_applicable' | 'unknown';

const availabilityLabels: Readonly<Record<DataAvailabilityState, string>> = {
  not_measured: 'Not measured',
  not_run: 'Not run',
  not_set: 'Not set',
  unavailable: 'Unavailable',
  not_applicable: 'Not applicable',
  unknown: 'Unknown',
};

/** Human-readable product vocabulary for explicit missing-data states. */
export function availabilityLabel(state: DataAvailabilityState): string {
  return availabilityLabels[state];
}

export const GRANULARITY_OPTIONS: readonly { value: BucketGranularity; label: string }[] = [
  { value: 'day', label: 'Day' },
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
] as const;

/** Adjective form used inside copy ("n = 12 weekly buckets"). */
export function bucketAdjective(granularity: BucketGranularity): string {
  return granularity === 'day' ? 'daily' : granularity === 'week' ? 'weekly' : 'monthly';
}

/** `2026-07-23` → `Jul 23` (series bucket labels + active-run windows). */
export function formatShortDate(isoDay: string): string {
  const date = new Date(`${isoDay}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return isoDay;
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

/** `2026-07-23` → `Jul 23, 2026` (window labels in notes). */
export function formatWindowDate(isoDay: string): string {
  const date = new Date(`${isoDay}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return isoDay;
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

/** Mono timestamp in the F5 idiom (`Jul 23, 2026 · 18:14 UTC`). */
export function formatUtcTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  const datePart = date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  });
  const timePart = date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'UTC',
  });
  return `${datePart} · ${timePart} UTC`;
}

const numberFormat = new Intl.NumberFormat('en-US');

/** Whole-number grouping for counts (`1,162,000`). */
export function formatCount(value: number): string {
  return numberFormat.format(value);
}

/** Split a URL into a muted host part + the remaining path for mono url cells. */
export function splitUrlParts(url: string): { host: string; rest: string } {
  try {
    const parsed = new URL(url);
    return { host: parsed.host, rest: `${parsed.pathname}${parsed.search}` || '/' };
  } catch {
    // Scheme-less or non-URL value: split the leading host segment if present.
    const match = /^([^/]+)(\/.*)?$/.exec(url);
    if (match && match[1].includes('.')) {
      return { host: match[1], rest: match[2] ?? '/' };
    }
    return { host: '', rest: url };
  }
}
