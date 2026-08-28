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
  success: 'bg-success-bg text-success-text border border-success-border/60',
  warning: 'bg-warning-bg text-warning-text border border-warning-border/60',
  danger: 'bg-danger-bg text-danger-text border border-danger-border/60',
  info: 'bg-info-bg text-info-text border border-info-border/60',
} as const;

export const sentimentBadge = {
  positive: 'bg-sentiment-positive-bg text-sentiment-positive-text border border-success-border/50',
  neutral: 'bg-sentiment-neutral-bg text-sentiment-neutral-text border border-border',
  negative: 'bg-sentiment-negative-bg text-sentiment-negative-text border border-danger-border/50',
} as const;

export const classificationBadge = {
  owned: 'bg-citation-owned-bg text-citation-owned-text border border-citation-owned-border/60',
  competitor:
    'bg-citation-competitor-bg text-citation-competitor-text border border-citation-competitor-border/60',
  'third-party':
    'bg-citation-third-party-bg text-citation-third-party-text border border-citation-third-party-border/60',
} as const;

export const runStatusBadge = {
  draft: 'bg-run-draft-bg text-run-draft border border-border',
  queued: 'bg-run-queued-bg text-run-queued border border-border',
  running: 'bg-run-running-bg text-run-running border border-accent-border/60',
  paused: 'bg-run-queued-bg text-run-queued border border-border',
  analyzing: 'bg-run-analyzing-bg text-run-analyzing border border-purple-200',
  completed: 'bg-run-completed-bg text-run-completed border border-success-border/60',
  partial: 'bg-run-partial-bg text-run-partial border border-warning-border/60',
  failed: 'bg-run-failed-bg text-run-failed border border-danger-border/60',
  cancelled: 'bg-run-cancelled-bg text-run-cancelled border border-border',
} as const;

export const neutralBadge = 'bg-neutral-bg text-secondary border border-border';

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
  'inline-flex items-center gap-1.5 whitespace-nowrap rounded-sm px-2 py-0.5 text-2xs font-semibold';

/** Run-status badges stay pills — the lifecycle dot reads better round. */
export const runStatusBadgeShape = 'rounded-full px-2';
