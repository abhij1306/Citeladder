import type { ComponentPropsWithoutRef } from 'react';

import { cn } from '@/lib/utils';

/**
 * Eyebrow (kicker) recipes — sans micro-labels at the product secondary rung
 * (12px / 16px line-height, medium, muted). No uppercase or tracking.
 *
 * What does **not** come back is the mono face — mono stays reserved for
 * values, so a call site must never re-add `font-mono` here (see the
 * carry-forward note on page-kind-scores.tsx).
 *
 * `eyebrowClasses` is the muted form, shared by page eyebrows, table headers,
 * panel labels, sidebar group labels and <CardEyebrow>; apply it to whatever
 * element is semantic at the call site. <AccentEyebrow> is the accent-toned
 * variant used atop setup and status pages.
 */
export const eyebrowClasses = 'font-sans text-xs font-medium text-muted';

export function AccentEyebrow({
  children,
  className,
  ...props
}: Readonly<ComponentPropsWithoutRef<'span'>>) {
  return (
    <span
      {...props}
      className={cn(eyebrowClasses, 'text-accent-text inline-flex items-center gap-1.5', className)}
    >
      {children}
    </span>
  );
}
