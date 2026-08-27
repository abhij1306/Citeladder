/**
 * Score-band mapping (§ score bands): low 0–24, mid 25–49, good 50–74,
 * high 75–100. Returns the bridged token utility classes for stroke/text
 * so data-viz primitives stay token-only (no raw hex). */
export type ScoreBand = 'low' | 'mid' | 'good' | 'high';

export function scoreBand(score: number): ScoreBand {
  if (score >= 75) return 'high';
  if (score >= 50) return 'good';
  if (score >= 25) return 'mid';
  return 'low';
}

/**
 * Ring/arc stroke per band. Points at the dedicated `--score-*-ring` tokens
 * rather than the solids: rings sit on a surface, not behind text, so the two
 * are free to diverge (and do, in dark).
 */
export const scoreBandStroke: Record<ScoreBand, string> = {
  low: 'stroke-score-low-ring',
  mid: 'stroke-score-mid-ring',
  good: 'stroke-score-good-ring',
  high: 'stroke-score-high-ring',
};

/**
 * Band as text. Uses the `--score-*-text` tokens, which are the AA-gated
 * variants — the solids are not guaranteed readable as type.
 */
export const scoreBandText: Record<ScoreBand, string> = {
  low: 'text-score-low-text',
  mid: 'text-score-mid-text',
  good: 'text-score-good-text',
  high: 'text-score-high-text',
};

/**
 * Null-aware text class for a score cell: muted for a missing score (which
 * renders the `Not measured` placeholder), the band colour otherwise. Shared by every
 * score table so the missing-score treatment never diverges.
 */
export function scoreTextClass(score: number | null): string {
  if (score === null) return 'text-muted';
  return scoreBandText[scoreBand(score)];
}
