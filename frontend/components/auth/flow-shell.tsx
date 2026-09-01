import { Check } from 'lucide-react';
import Link from 'next/link';
import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

import { AuthWordmark } from './brand-panel';

export type FlowStep = {
  id: string;
  label: string;
};

export function FlowShell({
  children,
  steps,
  currentStep = 0,
  actions,
  footer,
  exitHref,
  mainLabel,
  align = 'start',
  measure = 'default',
}: Readonly<{
  children: ReactNode;
  steps?: readonly FlowStep[];
  currentStep?: number;
  actions?: ReactNode;
  footer?: ReactNode;
  exitHref?: string;
  mainLabel: string;
  align?: 'start' | 'center';
  measure?: 'default' | 'wide';
}>) {
  return (
    <div
      data-flow-surface
      className="bg-background text-foreground grid h-dvh min-h-dvh grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden antialiased"
    >
      <FlowBar steps={steps} currentStep={currentStep} exitHref={exitHref} />
      <main id="main" aria-label={mainLabel} className="flow-main" data-flow-align={align}>
        <div className="flow-content" data-flow-measure={measure}>
          {children}
        </div>
      </main>
      {actions ?? (footer ? <footer className="flow-footer">{footer}</footer> : null)}
    </div>
  );
}

function FlowBar({
  steps,
  currentStep,
  exitHref,
}: Readonly<{
  steps?: readonly FlowStep[];
  currentStep: number;
  exitHref?: string;
}>) {
  return (
    <header className="flow-bar">
      <div className="flow-bar-content">
        <AuthWordmark compact />
        {steps ? <FlowProgress steps={steps} currentStep={currentStep} /> : <span />}
        {exitHref ? (
          <Link href={exitHref} className="flow-exit">
            Exit
          </Link>
        ) : (
          <span />
        )}
      </div>
      {steps ? (
        <div className="flow-progress-rule" aria-hidden="true">
          <span style={{ transform: `scaleX(${(currentStep + 1) / steps.length})` }} />
        </div>
      ) : null}
    </header>
  );
}

function FlowProgress({
  steps,
  currentStep,
}: Readonly<{ steps: readonly FlowStep[]; currentStep: number }>) {
  return (
    <nav aria-label="Setup progress" className="flow-progress">
      <ol>
        {steps.map((step, index) => {
          const isCurrent = index === currentStep;
          const isDone = index < currentStep;
          return (
            <li key={step.id} aria-current={isCurrent ? 'step' : undefined}>
              {index > 0 ? <span className="flow-step-connector" aria-hidden="true" /> : null}
              <span
                className={cn(
                  'flow-step-mark',
                  isCurrent && 'flow-step-mark-current',
                  isDone && 'flow-step-mark-done',
                )}
                aria-hidden="true"
              >
                {isDone ? <Check /> : index + 1}
              </span>
              <span className="flow-step-label">
                <span className="flow-step-mobile-prefix">
                  Step {index + 1} of {steps.length} ·{' '}
                </span>
                {step.label}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export function FlowActions({
  secondary,
  primary,
  wide = false,
}: Readonly<{ secondary?: ReactNode; primary: ReactNode; wide?: boolean }>) {
  return (
    <footer className="flow-actions safe-bottom">
      <div className="flow-action-content" data-flow-measure={wide ? 'wide' : 'default'}>
        <div>{secondary}</div>
        <div>{primary}</div>
      </div>
    </footer>
  );
}

export function FlowGroup({
  title,
  help,
  meta,
  action,
  className,
  children,
}: Readonly<{
  title: string;
  help?: ReactNode;
  meta?: ReactNode;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}>) {
  return (
    <section className={cn('flow-group', className)}>
      <div className="flow-group-heading">
        <div className="flow-group-copy">
          <h2 className="flow-group-title">{title}</h2>
          {help ? <p className="flow-help">{help}</p> : null}
        </div>
        {meta || action ? (
          <div className="flow-group-aside">
            {meta ? <span className="flow-meta">{meta}</span> : null}
            {action}
          </div>
        ) : null}
      </div>
      <div className="flow-answer">{children}</div>
    </section>
  );
}
