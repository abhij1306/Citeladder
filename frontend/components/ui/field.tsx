import { useId } from 'react';
import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

/**
 * Field (§8) — wraps a control with a label, optional hint, and an inline
 * error. The label is associated to the control via a generated id (passed
 * through the `children` render prop) for accessibility.
 */
export function Field({
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
    required?: boolean;
    'aria-invalid'?: boolean;
    'aria-describedby'?: string;
  }) => ReactNode;
}>) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy =
    [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(' ') || undefined;

  return (
    <div className={cn('grid gap-1', className)}>
      <label htmlFor={id} className="text-secondary text-xs font-semibold">
        {label}
        {required ? <span className="text-danger ms-0.5">*</span> : null}
      </label>
      {children({
        id,
        required,
        'aria-invalid': error ? true : undefined,
        'aria-describedby': describedBy,
      })}
      {hint && !error ? (
        <span id={hintId} className="text-muted text-xs">
          {hint}
        </span>
      ) : null}
      {error ? (
        <span id={errorId} role="alert" className="text-danger-text text-xs">
          {error}
        </span>
      ) : null}
    </div>
  );
}
