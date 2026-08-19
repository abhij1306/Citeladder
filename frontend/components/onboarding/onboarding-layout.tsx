import { Check } from 'lucide-react';

import { AuthWordmark, BrandCanvas } from '@/components/auth/brand-panel';
import { cn } from '@/lib/utils';

import type { OnboardingStep } from './onboarding-flow';

const STEPS = [
  { id: 'brand', title: 'Basic information', description: 'Name & domain details' },
  { id: 'discovery', title: 'AI Research', description: 'Auto-finding competitors' },
  { id: 'review', title: 'Confirm ICP', description: 'Finalize facts & tracking scope' },
] as const;

export const STEP_MAIN_ALIGNMENT = [
  'justify-start min-[900px]:pt-[3.25rem]',
  'justify-start min-[900px]:pt-[3.25rem]',
  'justify-center',
] as const;

function StepMarker({ index, step }: Readonly<{ index: number; step: OnboardingStep }>) {
  const isDone = index < step;
  const isCurrent = index === step;
  return (
    <span
      className={cn(
        'relative z-10 flex size-9 shrink-0 items-center justify-center rounded-full text-sm font-bold transition-all sm:size-10',
        isDone && 'bg-accent text-accent-fg shadow-accent/30 shadow-md',
        isCurrent && 'bg-accent text-accent-fg ring-accent/20 ring-4',
        !isDone &&
          !isCurrent &&
          'border-brand-canvas-border bg-brand-canvas-raised text-brand-canvas-muted border',
      )}
    >
      {isDone ? <Check className="size-4.5" strokeWidth={2.5} aria-hidden="true" /> : index + 1}
    </span>
  );
}

export function OnboardingSidebar({ step }: Readonly<{ step: OnboardingStep }>) {
  return (
    <BrandCanvas className="col-span-5 h-screen max-h-screen justify-between p-6 lg:col-span-4 xl:p-10">
      <div className="relative z-10 flex flex-col gap-8">
        <AuthWordmark light />
        <div className="space-y-1.5">
          <h2 className="website-feature-heading text-brand-canvas-foreground">
            Set up your project
          </h2>
          <p className="website-body text-brand-canvas-secondary">
            Create your workspace in a few clicks.
          </p>
        </div>
        <div className="relative my-auto">
          <div
            className="bg-brand-canvas-border absolute top-4 bottom-4 left-4.5 w-0.5"
            aria-hidden="true"
          />
          <ol className="relative list-none space-y-10 p-0 pl-1 sm:space-y-12">
            {STEPS.map((stage, index) => {
              const isDone = index < step;
              const isCurrent = index === step;
              return (
                <li
                  key={stage.id}
                  aria-current={isCurrent ? 'step' : undefined}
                  className="relative flex items-center gap-4"
                >
                  <StepMarker index={index} step={step} />
                  <div className="space-y-1">
                    <p
                      className={cn(
                        'website-small-heading transition-colors',
                        isCurrent && 'text-brand-canvas-foreground',
                        isDone && 'text-brand-canvas-secondary',
                        !isDone && !isCurrent && 'text-brand-canvas-muted',
                      )}
                    >
                      {stage.title}
                    </p>
                    <p className="website-label text-brand-canvas-muted">{stage.description}</p>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
      <div className="website-label border-brand-canvas-border/80 text-brand-canvas-muted relative z-10 border-t pt-4">
        <span>© {new Date().getFullYear()} CiteLadder · Onboarding</span>
      </div>
    </BrandCanvas>
  );
}

export function OnboardingMobileHeader({ step }: Readonly<{ step: OnboardingStep }>) {
  return (
    <header className="border-border-subtle border-b pb-3 min-[900px]:hidden">
      <div className="flex items-center justify-between gap-4">
        <AuthWordmark compact />
        <ol className="flex list-none items-center gap-2 p-0">
          {STEPS.map((stage, index) => {
            const state = index < step ? 'done' : index === step ? 'current' : 'upcoming';
            return (
              <li key={stage.id} className="flex items-center">
                <span
                  aria-current={state === 'current' ? 'step' : undefined}
                  className={cn(
                    'flex size-6 items-center justify-center rounded-full text-xs font-semibold',
                    state === 'current'
                      ? 'bg-accent text-accent-fg'
                      : state === 'done'
                        ? 'bg-success text-accent-fg'
                        : 'border-border-subtle bg-well text-muted border',
                  )}
                >
                  {state === 'done' ? (
                    <Check className="size-3" strokeWidth={3} aria-hidden="true" />
                  ) : (
                    index + 1
                  )}
                  <span className="sr-only">{stage.title}</span>
                </span>
              </li>
            );
          })}
        </ol>
      </div>
    </header>
  );
}
