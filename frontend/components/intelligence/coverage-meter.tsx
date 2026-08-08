import { cn } from '@/lib/utils';

import { StateLabel } from './state-label';

/**
 * CoverageMeter — the §6 rule, implemented once.
 *
 * Composites render over the FULL denominator with coverage beside them. This
 * component never renormalizes, and it does not expose an option to.
 *
 * Why: renormalizing over observed dimensions assumes the missing ones would
 * have scored like the observed ones, and in this domain that fails
 * predictably — absent evidence correlates with weakness. A site with no
 * schema graph, no policy pages, and no author attribution is missing exactly
 * the dimensions it would have failed, so renormalizing scores it above a site
 * that published all three and scored badly.
 *
 * Low coverage is therefore presented as a finding in its own right, not as a
 * footnote under a flattering number.
 */

/** Below this, coverage is surfaced as a finding rather than a footnote. */
export const LOW_COVERAGE_THRESHOLD = 0.6;

export type CoverageMeterProps = {
  /**
   * Score over the FULL denominator, 0–1. Callers pass the un-renormalized
   * value; this component cannot compute it for them because only the caller
   * knows the full dimension set.
   */
  score: number;
  /** Dimensions actually observed. */
  observed: number;
  /** Total dimensions in the full denominator. */
  total: number;
  /** Accessible name for the score, e.g. "Site health". */
  label: string;
  className?: string;
};

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function CoverageMeter({
  score,
  observed,
  total,
  label,
  className,
}: Readonly<CoverageMeterProps>) {
  // A zero denominator is not a zero score — nothing was measurable at all.
  if (total <= 0) {
    return (
      <figure className={cn('m-0 flex flex-col gap-1', className)}>
        <figcaption className="text-muted text-xs font-medium">{label}</figcaption>
        <StateLabel state="unavailable" />
      </figure>
    );
  }

  const coverage = observed / total;
  const isLowCoverage = coverage < LOW_COVERAGE_THRESHOLD;

  return (
    // <figure> + <figcaption> gives the score an accessible name natively; a
    // bare percentage in a sibling <p> has none, and role="group" would trip
    // the "prefer a native element" lint.
    <figure className={cn('m-0 flex flex-col gap-1.5', className)}>
      <figcaption className="text-muted text-xs font-medium">{label}</figcaption>

      {/* Score and coverage are two numbers read together — never one number
          with the other hidden in a tooltip. */}
      <div className="flex items-baseline gap-2">
        <span className="text-foreground text-2xl font-semibold tabular-nums">
          {formatPercent(score)}
        </span>
        <span className="text-muted text-xs tabular-nums">
          {observed} of {total} measured
        </span>
      </div>

      {isLowCoverage ? (
        <p className="text-warning-text text-2xs font-medium">
          Low coverage — {formatPercent(coverage)} of dimensions observed. Unmeasured dimensions
          count against this score rather than being excluded from it.
        </p>
      ) : null}
    </figure>
  );
}
