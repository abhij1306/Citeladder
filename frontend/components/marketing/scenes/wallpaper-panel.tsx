import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

/**
 * The recurring product surface. Tonal contrast and spacing carry hierarchy;
 * shadows remain reserved for genuinely floating UI.
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
        'bg-background-alt relative overflow-hidden',
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
 * Scene window — the white panel that sits on the tonal wallpaper.
 */
export function Panel({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  return <div className={cn('bg-panel rounded-[var(--radius-card)]', className)}>{children}</div>;
}
