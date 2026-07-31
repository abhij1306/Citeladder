import { AlertCircle } from 'lucide-react';
import { useId } from 'react';
import type { ComponentPropsWithoutRef, ReactNode } from 'react';

import { cn } from '@/lib/utils';

/**
 * Form controls for the Proof surface (auth screens). Same accessibility
 * contract as the app's Field — generated id, `aria-invalid`, and a
 * `role="alert"` error wired through `aria-describedby` — restyled onto the
 * marketing tokens so the logged-out funnel is one visual system end to end.
 */
export function MktField({
  label,
  hint,
  error,
  required,
  className,
  children,
}: Readonly<{
  label: string;
  hint?: string;
  error?: ReactNode;
  required?: boolean;
  className?: string;
  children: (props: {
    id: string;
    'aria-invalid'?: boolean;
    'aria-describedby'?: string;
  }) => ReactNode;
}>) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  // The hint is only RENDERED when there is no error, so pointing
  // aria-describedby at it in the error case would reference a missing node.
  const describedBy =
    [error ? errorId : null, hint && !error ? hintId : null].filter(Boolean).join(' ') || undefined;

  return (
    <div className={cn('grid gap-2', className)}>
      <label htmlFor={id} className="text-mkt-sm text-mkt-ink-soft font-bold">
        {label}
        {required && (
          <span aria-hidden className="text-mkt-signal-text ml-0.5">
            *
          </span>
        )}
      </label>
      {children({
        id,
        'aria-invalid': error ? true : undefined,
        'aria-describedby': describedBy,
      })}
      {hint && !error && (
        <span id={hintId} className="text-mkt-sm text-mkt-ink-muted">
          {hint}
        </span>
      )}
      {error && (
        <span id={errorId} role="alert" className="text-mkt-sm text-mkt-signal-text">
          {error}
        </span>
      )}
    </div>
  );
}

export function MktInput({ className, ...props }: ComponentPropsWithoutRef<'input'>) {
  return (
    <input
      {...props}
      className={cn(
        'border-mkt-line bg-mkt-paper-raised text-mkt-ink placeholder:text-mkt-ink-muted rounded-mkt-sm',
        'focus:border-mkt-proof focus:ring-mkt-proof-soft text-mkt-body min-h-12 w-full border px-4',
        'transition-[border-color,box-shadow,background-color] duration-200 outline-none',
        'focus:bg-mkt-surface aria-invalid:border-mkt-signal focus:ring-2',
        className,
      )}
    />
  );
}

/** Inline form error banner — the only alert tone the auth screens need. */
export function MktAlert({ children }: Readonly<{ children: ReactNode }>) {
  if (!children) return null;
  return (
    <div
      role="alert"
      className="border-mkt-signal-line bg-mkt-signal-soft text-mkt-signal-text rounded-mkt-sm text-mkt-sm flex gap-3 border p-4"
    >
      <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0">{children}</div>
    </div>
  );
}
