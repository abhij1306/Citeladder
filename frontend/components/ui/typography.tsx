import type { ComponentPropsWithoutRef } from 'react';

import { eyebrowClasses } from '@/components/ui/eyebrow';
import { cn } from '@/lib/utils';

/**
 * Heading recipes: `displayHeadingLgClasses` for panel / empty-state headings
 * (20/28 @600), and `displayHeadingXlClasses`
 * for page titles (24/32 @600). There is no
 * separate display face, so headings differ from body by size and weight only,
 * and both rungs bake their weight into the `--text-*` token. These are class
 * recipes, not components — the call site keeps whichever heading element is
 * semantic.
 */
export const displayHeadingLgClasses = 'font-display text-lg font-medium text-foreground';
export const displayHeadingXlClasses = 'font-display text-2xl font-medium text-foreground';

/** Section heading (card / block level). */
export function SectionTitle({
  children,
  className,
  ...props
}: Readonly<ComponentPropsWithoutRef<'h2'>>) {
  return (
    <h2 {...props} className={cn('font-display text-foreground text-base font-medium', className)}>
      {children}
    </h2>
  );
}

/** Sentence-case micro-label (the same recipe as `eyebrowClasses`). */
export function Label({
  children,
  className,
  ...props
}: Readonly<ComponentPropsWithoutRef<'span'>>) {
  return (
    <span {...props} className={cn(eyebrowClasses, className)}>
      {children}
    </span>
  );
}

/** Mono metric value with tabular numerals. */
export function Metric({
  children,
  className,
  ...props
}: Readonly<ComponentPropsWithoutRef<'span'>>) {
  return (
    <span
      {...props}
      className={cn(
        'mono font-display text-foreground text-3xl font-medium tracking-[-0.02em] tabular-nums',
        className,
      )}
    >
      {children}
    </span>
  );
}
