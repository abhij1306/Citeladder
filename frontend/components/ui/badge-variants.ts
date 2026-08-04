/**
 * Badge token maps (§8). Each family maps a value → bridged semantic token
 * classes (bg + text + border). No raw hex; all classes resolve to the
 * semantic Tailwind declarations in globals.css.
 *
 * Families:
 *  - status:         success | warning | danger | info
 *  - sentiment:      positive | neutral | negative
 *  - classification: owned | competitor | third-party  (citation classification)
 *  - run-status:     draft | queued | running | analyzing | completed | partial | failed | cancelled
 *  - neutral:        the default grey chip
 */

export const statusBadge = {
  success: 'bg-success-bg text-success-text',
  warning: 'bg-warning-bg text-warning-text',
  danger: 'bg-danger-bg text-danger-text',
  info: 'bg-info-bg text-info-text',
} as const;

export const sentimentBadge = {
  positive: 'bg-sentiment-positive-bg text-sentiment-positive-text',
  neutral: 'bg-sentiment-neutral-bg text-sentiment-neutral-text',
  negative: 'bg-sentiment-negative-bg text-sentiment-negative-text',
} as const;

export const classificationBadge = {
  owned: 'bg-citation-owned-bg text-citation-owned-text',
  competitor: 'bg-citation-competitor-bg text-citation-competitor-text',
  'third-party': 'bg-citation-third-party-bg text-citation-third-party-text',
} as const;

export const runStatusBadge = {
  draft: 'bg-run-draft-bg text-run-draft',
  queued: 'bg-run-queued-bg text-run-queued',
  running: 'bg-run-running-bg text-run-running',
  analyzing: 'bg-run-analyzing-bg text-run-analyzing',
  completed: 'bg-run-completed-bg text-run-completed',
  partial: 'bg-run-partial-bg text-run-partial',
  failed: 'bg-run-failed-bg text-run-failed',
  cancelled: 'bg-run-cancelled-bg text-run-cancelled',
} as const;

export const neutralBadge = 'bg-neutral-bg text-secondary';

export type StatusValue = keyof typeof statusBadge;
export type SentimentValue = keyof typeof sentimentBadge;
export type ClassificationValue = keyof typeof classificationBadge;
export type RunStatusValue = keyof typeof runStatusBadge;

/**
 * Shared shape/typography for every badge family — flat sans rectangles
 * (rounded-sm), not mono pills. Casing comes from the call site so product
 * nouns keep their capitalization. `run-status` keeps the pill via
 * `runStatusBadgeShape` below.
 */
export const badgeBase =
  'inline-flex items-center gap-1 whitespace-nowrap rounded-sm px-1 py-0.5 text-2xs font-semibold';

/** Run-status badges stay pills — the lifecycle dot reads better round. */
export const runStatusBadgeShape = 'rounded-full';
