import { Badge } from '@/components/ui/badge';
import type { CoverageState } from '@/lib/api/types';

/**
 * How each of the eight coverage states is shown.
 *
 * The states are DISTINCT and the UI keeps them that way. In particular:
 *
 * - `unavailable_evidence` is INFO, not danger. It says the pages that would
 *   answer this could not be acquired — the site is not being judged, so
 *   colouring it like a failure would blame a customer for our crawl.
 * - `unsupported` is warning, and it is the one most worth acting on: the page
 *   exists and states none of the required facts.
 * - `conflicting` is danger even though facts EXIST, because a contradicted
 *   answer can be published and a missing one cannot.
 * - `not_applicable` is neutral: a reviewer declared it out of scope, and it is
 *   the only state removed from the coverage denominator.
 */
const COVERAGE_PRESENTATION: Record<
  CoverageState,
  { label: string; tone: 'success' | 'warning' | 'danger' | 'info' | 'neutral' }
> = {
  answered_strong: { label: 'Answered', tone: 'success' },
  answered_weak: { label: 'Partly answered', tone: 'warning' },
  missing: { label: 'Missing', tone: 'danger' },
  conflicting: { label: 'Conflicting', tone: 'danger' },
  unsupported: { label: 'Unsupported', tone: 'warning' },
  historical_only: { label: 'Historical only', tone: 'warning' },
  unavailable_evidence: { label: 'Evidence unavailable', tone: 'info' },
  not_applicable: { label: 'Not applicable', tone: 'neutral' },
};

/**
 * A state this build does not know about still renders — as itself, neutrally.
 *
 * The schema strips unknown keys but a NEW coverage state is a valid enum value
 * the backend may ship first. Indexing blind would throw and take the whole
 * panel down; showing the raw token is honest and keeps the rest readable.
 */
function presentationFor(state: CoverageState) {
  return (
    COVERAGE_PRESENTATION[state] ?? {
      label: String(state).replaceAll('_', ' '),
      tone: 'neutral' as const,
    }
  );
}

export function CoverageBadge({ state }: Readonly<{ state: CoverageState }>) {
  const presentation = presentationFor(state);
  if (presentation.tone === 'neutral') {
    return <Badge>{presentation.label}</Badge>;
  }
  return (
    <Badge variant="status" value={presentation.tone}>
      {presentation.label}
    </Badge>
  );
}

export function coverageLabel(state: CoverageState): string {
  return presentationFor(state).label;
}

/**
 * Render a 0–1 ratio as a percentage, or an explicit "not measurable".
 *
 * `null` and `0` are different facts everywhere in this feature, so this never
 * coalesces: a component that showed "0%" for an unmeasurable dimension would
 * report a failing site where there is simply nothing to measure yet.
 */
export function Ratio({
  value,
  unavailableLabel = 'Not measurable',
}: Readonly<{ value: number | null; unavailableLabel?: string }>) {
  if (value === null) {
    return <span className="text-muted text-sm">{unavailableLabel}</span>;
  }
  return <span className="text-foreground tabular-nums">{Math.round(value * 100)}%</span>;
}

/**
 * A score and its coverage, always together.
 *
 * Composites here are computed over the FULL denominator, so a low score can
 * mean "did badly" or "we could only observe a third of it". Showing the score
 * without its coverage hides which one, and that ambiguity is exactly what the
 * full-denominator rule exists to expose.
 */
export function ScoreWithCoverage({
  score,
  coverage,
  label,
}: Readonly<{ score: number | null; coverage: number | null; label: string }>) {
  return (
    <div className="grid gap-0.5">
      <span className="text-muted text-2xs tracking-wide uppercase">{label}</span>
      <span className="text-heading-sm text-foreground tabular-nums">
        <Ratio value={score} unavailableLabel="—" />
      </span>
      <span className="text-muted text-2xs">
        <Ratio value={coverage} unavailableLabel="coverage unknown" /> of this was observable
      </span>
    </div>
  );
}
