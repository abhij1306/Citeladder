'use client';

import { Check, CircleAlert } from 'lucide-react';
import { useEffect, useMemo, useState, useSyncExternalStore } from 'react';

import { cn } from '@/lib/utils';

type ActivityStepState = 'complete' | 'active' | 'pending' | 'attention';

export type ActivityStep = {
  id: string;
  label: string;
  detail?: string;
  state: ActivityStepState;
};

function StepIndicator({ state }: Readonly<{ state: ActivityStepState }>) {
  if (state === 'complete') return <Check className="size-4" strokeWidth={3} />;
  if (state === 'attention') return <CircleAlert className="size-4" />;
  if (state === 'active') return <span className="activity-dot bg-accent size-2" />;
  return <span className="bg-border-subtle size-1.5 rounded-full" />;
}

function progressAnnouncement(activeStep: ActivityStep | undefined, completed: number): string {
  if (!activeStep) return `${completed} steps complete`;
  return `${activeStep.label}. ${activeStep.detail ?? ''}`;
}

function subscribeToReducedMotion(onChange: () => void) {
  const media = window.matchMedia('(prefers-reduced-motion: reduce)');
  media.addEventListener('change', onChange);
  return () => media.removeEventListener('change', onChange);
}

function reducedMotionSnapshot() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * A compact, factual timeline for background product work.
 *
 * Callers own the mapping from API phases to user language. This component
 * deliberately knows nothing about queue states or worker vocabulary, which
 * prevents an internal token from becoming fallback UI copy.
 */
export function ActivityProgress({
  steps,
  label,
  animateCompletion = false,
}: Readonly<{
  steps: ActivityStep[];
  label: string;
  /** Reveal fast persisted phase jumps one step at a time. */
  animateCompletion?: boolean;
}>) {
  const targetCompleted = steps.filter((step) => step.state === 'complete').length;
  const [displayedCompleted, setDisplayedCompleted] = useState(
    animateCompletion ? 0 : targetCompleted,
  );
  const reduceMotion = useSyncExternalStore(
    subscribeToReducedMotion,
    reducedMotionSnapshot,
    () => false,
  );
  const shouldAnimate = animateCompletion && !reduceMotion;

  useEffect(() => {
    if (!shouldAnimate) return;
    if (displayedCompleted > targetCompleted) {
      const resetTimer = window.setTimeout(() => setDisplayedCompleted(targetCompleted), 0);
      return () => window.clearTimeout(resetTimer);
    }
    if (displayedCompleted === targetCompleted) return;
    const timer = window.setTimeout(
      () => setDisplayedCompleted((current) => Math.min(current + 1, targetCompleted)),
      360,
    );
    return () => window.clearTimeout(timer);
  }, [displayedCompleted, shouldAnimate, targetCompleted]);

  const renderedSteps = useMemo(() => {
    if (!shouldAnimate || displayedCompleted >= targetCompleted) return steps;
    return steps.map((step, index): ActivityStep => {
      if (step.state === 'attention') return step;
      return {
        ...step,
        state:
          index < displayedCompleted
            ? 'complete'
            : index === displayedCompleted
              ? 'active'
              : 'pending',
      };
    });
  }, [displayedCompleted, shouldAnimate, steps, targetCompleted]);

  const completed = renderedSteps.filter((step) => step.state === 'complete').length;
  const activeStep = renderedSteps.find(
    (step) => step.state === 'active' || step.state === 'attention',
  );
  const progressLabel = `${completed} of ${steps.length} steps complete`;

  return (
    <section aria-label={label} className="grid gap-4">
      <progress
        className="bg-neutral-bg [&::-webkit-progress-bar]:bg-neutral-bg [&::-webkit-progress-value]:bg-accent [&::-moz-progress-bar]:bg-accent h-1.5 w-full appearance-none overflow-hidden rounded-full border-0"
        aria-label={progressLabel}
        aria-valuemin={0}
        aria-valuemax={steps.length}
        aria-valuenow={completed}
        value={completed}
        max={Math.max(renderedSteps.length, 1)}
      />

      <ol className="grid list-none gap-0 p-0">
        {renderedSteps.map((step, index) => (
          <li key={step.id} className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-3">
            <div className="flex flex-col items-center" aria-hidden>
              <span
                className={cn(
                  'relative z-1 flex size-6 shrink-0 items-center justify-center rounded-full',
                  step.state === 'complete' && 'bg-success text-accent-fg',
                  step.state === 'active' && 'bg-accent-subtle text-accent-text',
                  step.state === 'attention' && 'bg-warning-bg text-warning-text',
                  step.state === 'pending' && 'border-border-subtle bg-panel text-muted border',
                )}
              >
                <StepIndicator state={step.state} />
              </span>
              {index < renderedSteps.length - 1 ? (
                <span className="bg-border-subtle min-h-5 w-px flex-1" />
              ) : null}
            </div>

            <div className={cn('min-w-0 pb-4', index === renderedSteps.length - 1 && 'pb-0')}>
              <p
                className={cn(
                  'text-sm font-medium',
                  step.state === 'pending' ? 'text-muted' : 'text-foreground',
                )}
              >
                {step.label}
              </p>
              {step.detail ? <p className="text-secondary mt-0.5 text-xs">{step.detail}</p> : null}
            </div>
          </li>
        ))}
      </ol>

      <span className="sr-only" aria-live="polite">
        {progressAnnouncement(activeStep, completed)}
      </span>
    </section>
  );
}
