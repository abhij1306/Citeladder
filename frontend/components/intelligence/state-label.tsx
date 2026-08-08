import type { HTMLAttributes } from 'react';

import { cn } from '@/lib/utils';

/**
 * StateLabel — the vocabulary for "this number is not a number".
 *
 * Nine states, each with distinct TEXT (design.md: status colour never carries
 * meaning alone; WCAG 1.4.1). The whole point of this component is that the
 * states are not interchangeable: `unavailable` means we could not measure,
 * `not_applicable` means the question does not apply here, and `observed_zero`
 * means we measured and the answer was zero. Those three render as an empty
 * chart if a screen is careless, which is exactly the confusion this prevents.
 *
 * Rendering the state as a shared component rather than per-screen strings is
 * what stops the vocabulary drifting apart across the four layers.
 */
export const DERIVED_STATES = [
  'unknown',
  'unavailable',
  'not_applicable',
  'historical',
  'future',
  'conflicting',
  'excluded',
  'failed',
  'observed_zero',
] as const;

export type DerivedState = (typeof DERIVED_STATES)[number];

/**
 * Label and explanation per state. The label is what renders; the description
 * is the title/tooltip, because the distinction between these states is the
 * part users get wrong.
 */
const STATE_COPY: Record<DerivedState, { label: string; description: string }> = {
  unknown: {
    label: 'Unknown',
    description: 'Not yet determined. No observation has been attempted.',
  },
  unavailable: {
    label: 'Unavailable',
    description: 'Could not be measured — the source did not return a usable value.',
  },
  not_applicable: {
    label: 'Not applicable',
    description: 'This measure does not apply to this artifact.',
  },
  historical: {
    label: 'Historical',
    description: 'Was true in an earlier period and is not asserted as current.',
  },
  future: {
    label: 'Scheduled',
    description: 'Takes effect at a future date and is not current.',
  },
  conflicting: {
    label: 'Conflicting',
    description: 'Sources disagree. No single value is asserted.',
  },
  excluded: {
    label: 'Excluded',
    description: 'Deliberately outside the analyzed scope.',
  },
  failed: {
    label: 'Failed',
    description: 'The attempt ran and did not complete.',
  },
  observed_zero: {
    label: 'Zero observed',
    description: 'Measured successfully. The observed value is zero.',
  },
};

/**
 * Tone maps to the semantic status families. Colour is redundant with the
 * label by construction — never the only signal.
 */
const STATE_TONE: Record<DerivedState, string> = {
  unknown: 'bg-neutral-bg text-secondary',
  unavailable: 'bg-neutral-bg text-secondary',
  not_applicable: 'bg-neutral-bg text-secondary',
  historical: 'bg-info-bg text-info-text',
  future: 'bg-info-bg text-info-text',
  conflicting: 'bg-warning-bg text-warning-text',
  excluded: 'bg-neutral-bg text-secondary',
  failed: 'bg-danger-bg text-danger-text',
  observed_zero: 'bg-neutral-bg text-secondary',
};

export function stateLabel(state: DerivedState): string {
  return STATE_COPY[state].label;
}

export type StateLabelProps = {
  state: DerivedState;
  /** Overrides the default label. Use only when a surface has a truer word. */
  children?: string;
  className?: string;
} & Omit<HTMLAttributes<HTMLSpanElement>, 'children'>;

export function StateLabel({ state, children, className, ...rest }: Readonly<StateLabelProps>) {
  const { label, description } = STATE_COPY[state];
  return (
    <span
      className={cn(
        'text-2xs inline-flex items-center gap-1 rounded-sm px-1 py-0.5 font-medium whitespace-nowrap',
        STATE_TONE[state],
        className,
      )}
      title={description}
      data-state={state}
      {...rest}
    >
      {children ?? label}
    </span>
  );
}
