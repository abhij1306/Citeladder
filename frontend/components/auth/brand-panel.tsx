import Link from 'next/link';
import type { ReactNode } from 'react';

import { LogoMark } from '@/components/ui/logo-mark';
import { cn } from '@/lib/utils';

export function AuthWordmark({
  compact = false,
}: Readonly<{ compact?: boolean; light?: boolean }>) {
  return (
    <Link
      href="/"
      aria-label="CiteLadder home"
      className="group inline-flex items-center no-underline transition-opacity hover:opacity-90"
    >
      <LogoMark size={compact ? 22 : 26} />
    </Link>
  );
}

/**
 * The dark half of a split auth or onboarding screen.
 *
 * Shared rather than copied: auth and onboarding present the SAME brand
 * surface, and two hand-tuned stacks of glow and ribbon geometry drifted apart
 * the moment either was touched. Callers supply only the content; the ambient
 * treatment and the `min-[900px]` split point live here once.
 *
 * Colours come from the `brand-canvas-*` tokens. This is the one surface in the
 * app that stays dark in every theme, so it needs named roles — raw palette
 * classes describe a shade no theme can reach.
 */
export function BrandCanvas({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  return (
    <div
      data-brand-canvas="true"
      className={cn(
        'bg-brand-canvas text-brand-canvas-foreground relative flex flex-col overflow-hidden max-[900px]:hidden',
        className,
      )}
    >
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
        <div className="from-brand-canvas-glow/20 via-brand-canvas/80 to-brand-canvas absolute -top-1/4 -left-1/4 size-[150%] rounded-full bg-radial blur-3xl" />
        <div className="bg-accent/10 absolute top-1/2 left-1/2 size-96 -translate-x-1/2 -translate-y-1/2 rounded-full blur-[100px]" />
        <div className="border-brand-canvas-border/40 absolute top-1/3 -left-20 h-96 w-[600px] -rotate-12 rounded-[100px] border-2" />
        <div className="border-brand-canvas-border/30 absolute top-1/4 -left-10 h-96 w-[650px] -rotate-12 rounded-[120px] border" />
      </div>
      {children}
    </div>
  );
}

export function AuthBrandPanel() {
  return (
    <BrandCanvas className="col-span-1 min-h-full items-center justify-center px-8 py-12">
      <div className="relative z-10 flex items-center justify-center">
        <AuthWordmark light />
      </div>
    </BrandCanvas>
  );
}
