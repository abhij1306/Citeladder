/**
 * AI Referrals toolbar vocabulary: the date-range presets and snapshot
 * granularity driving the `/ai-referrals` screen.
 *
 * The range presets are OWNED here, mirroring the traffic surface's
 * `lib/traffic/traffic.ts` contract (the sibling snapshot surface, invariant
 * 2): the default `latest` preset sends NO window bounds so the backend
 * serves the project's freshest persisted snapshot, and bounded presets send
 * an exact `from`/`to` UTC-date window. The AI Referrals API binds `from`/`to`
 * as calendar `date`s supplied both-or-neither, so the visibility trend's
 * from-only ISO-datetime `rangeToFrom` (its endpoint filters run timestamps)
 * is NOT reusable here. This module also carries the AI-referrals-specific
 * granularity vocabulary (`day | week | month` — the backend
 * `snapshotGranularitySchema`, NOT the visibility trend's `run | week |
 * month`) plus the bucket-count labels the cards use.
 */
import type { z } from 'zod';

import type { snapshotGranularitySchema } from '@/lib/api/schemas';
import { bucketAdjective } from '@/lib/format';

/**
 * Date-range presets. `latest` sends NO window bounds — the backend serves
 * the project's latest persisted snapshot at the requested granularity, so
 * the default landing always renders the freshest projection. The bounded
 * presets send an exact `from`/`to` window (read endpoints serve persisted
 * snapshot windows only; an unmatched window yields the empty payload, which
 * the screen surfaces honestly rather than recomputing).
 */
export type AiReferralsRange = 'latest' | '30d' | '90d' | '1y';

export const RANGE_OPTIONS: readonly { value: AiReferralsRange; label: string }[] = [
  { value: 'latest', label: 'Latest synced window' },
  { value: '30d', label: 'Last 30 days' },
  { value: '90d', label: 'Last 90 days' },
  { value: '1y', label: 'Last 12 months' },
] as const;

export function rangeLabel(value: AiReferralsRange): string {
  return RANGE_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

const RANGE_DAYS: Record<Exclude<AiReferralsRange, 'latest' | '1y'>, number> = {
  '30d': 30,
  '90d': 90,
};

/** YYYY-MM-DD in UTC (the `date` query-param shape the API binds). */
function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/**
 * Resolve a range preset into `from`/`to` UTC date bounds, or `{}` for the
 * default latest-snapshot mode. `now` is injectable for deterministic tests.
 */
export function rangeToWindow(
  range: AiReferralsRange,
  now: Date = new Date(),
): { from?: string; to?: string } {
  if (range === 'latest') return {};
  const from = new Date(now.getTime());
  if (range === '1y') from.setUTCFullYear(from.getUTCFullYear() - 1);
  else from.setUTCDate(from.getUTCDate() - RANGE_DAYS[range]);
  return { from: isoDate(from), to: isoDate(now) };
}

// The granularity options + adjective form are OWNED by `@/lib/format`
// (shared with the traffic surface, invariant 2) — re-exported here.
export { bucketAdjective, GRANULARITY_OPTIONS } from '@/lib/format';

/** Snapshot bucket granularity — mirrors the backend contract vocabulary. */
export type AiReferralsGranularity = z.infer<typeof snapshotGranularitySchema>;

/** Capitalized adjective for sentence-start copy ("Weekly visibility score…"). */
export function bucketAdjectiveTitle(granularity: AiReferralsGranularity): string {
  const adjective = bucketAdjective(granularity);
  return adjective.charAt(0).toUpperCase() + adjective.slice(1);
}

/** Bucket-count badge label ("13 weeks", "1 day"). */
export function bucketCountLabel(granularity: AiReferralsGranularity, count: number): string {
  const noun = granularity === 'day' ? 'day' : granularity === 'week' ? 'week' : 'month';
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}
