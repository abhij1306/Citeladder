import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

/**
 * The recurring product surface. The marketing shell owns the single animated
 * atmosphere; scene cards stay opaque so the wallpaper never repeats inside
 * them.
 */
export function WallpaperPanel({
  children,
  className,
  rounded = true,
  ...rest
}: Readonly<{
  children: ReactNode;
  className?: string;
  rounded?: boolean;
  id?: string;
  'aria-hidden'?: boolean;
}>) {
  return (
    <div
      className={cn(
        'bg-background-alt shadow-card relative overflow-hidden',
        rounded && 'rounded-lg',
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

/**
 * Scene window — the white panel that sits on the wallpaper. Borderless by
 * rule (docs/design.md §4a): an opaque surface carried by the `shadow-card`
 * rung, no border, no glass, no blur.
 */
export function Panel({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  return <div className={cn('bg-panel shadow-card rounded-md', className)}>{children}</div>;
}
