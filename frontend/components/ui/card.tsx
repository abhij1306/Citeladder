import type { ComponentPropsWithoutRef, ReactNode } from 'react';

import { eyebrowClasses } from '@/components/ui/eyebrow';
import { cn } from '@/lib/utils';
import { cardClasses, type CardTone } from './card-variants';

/**
 * Card is reserved for a meaningful semantic object. It owns a white fill and
 * 16px object radius, with no default border or elevation. Structural layout
 * uses metric groups, ledgers, editorial sections, and workspace panes.
 *
 * Optional eyebrow header hook: render <CardEyebrow> above <CardTitle> for the
 * micro-label — e.g.
 *   <CardHeader><CardEyebrow>Visibility score</CardEyebrow><CardTitle>…
 */
export function Card({
  children,
  className,
  tone = 'default',
  ...props
}: Readonly<ComponentPropsWithoutRef<'section'> & { tone?: CardTone }>) {
  return (
    <section {...props} className={cn(cardClasses(tone), className)}>
      {children}
    </section>
  );
}

/**
 * CardHeader — no bottom rule by default (the editorial language separates the
 * header from content with spacing alone). Pass `bordered` for the few
 * surfaces that genuinely need the hairline, e.g. a header sitting directly
 * atop a full-bleed table.
 */
export function CardHeader({
  children,
  className,
  bordered,
  ...props
}: Readonly<ComponentPropsWithoutRef<'header'> & { bordered?: boolean }>) {
  return (
    <header
      {...props}
      className={cn(
        'flex flex-col gap-1 p-[var(--card-padding)] pb-2',
        bordered && 'border-border-subtle border-b pb-3',
        className,
      )}
    >
      {children}
    </header>
  );
}

/**
 * CardEyebrow — optional micro-label for card headers. Pair with CardTitle;
 * never a heading element.
 */
export function CardEyebrow({
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

export function CardTitle({
  children,
  className,
  ...props
}: Readonly<ComponentPropsWithoutRef<'h3'>>) {
  return (
    <h3 {...props} className={cn('font-display text-foreground text-lg font-medium', className)}>
      {children}
    </h3>
  );
}

export function CardDescription({
  children,
  className,
  ...props
}: Readonly<ComponentPropsWithoutRef<'p'>>) {
  return (
    <p {...props} className={cn('text-muted text-sm leading-relaxed', className)}>
      {children}
    </p>
  );
}

export function CardContent({
  children,
  className,
  ...props
}: Readonly<ComponentPropsWithoutRef<'div'> & { children: ReactNode }>) {
  return (
    <div {...props} className={cn('p-[var(--card-padding)]', className)}>
      {children}
    </div>
  );
}
