'use client';

import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

/**
 * Tooltip (§8) — Radix. The ADS inverse chip: a dark `bg-surface-inverse`
 * fill with `text-on-inverse` copy and NO border (an inverse chip needs
 * none), so it reads against every surface including a white card (the
 * Phase 1 `bg-elevated` version was ΔE 0.00 against one). Wrap the app (or a
 * subtree) once in <TooltipProvider>; each Tooltip pairs a trigger with
 * short text `content`.
 */
export const TooltipProvider = TooltipPrimitive.Provider;

export function Tooltip({
  children,
  content,
  side = 'top',
  align = 'center',
  className,
  delayDuration = 200,
}: Readonly<{
  children: ReactNode;
  content: ReactNode;
  side?: 'top' | 'right' | 'bottom' | 'left';
  align?: 'start' | 'center' | 'end';
  className?: string;
  delayDuration?: number;
}>) {
  return (
    <TooltipPrimitive.Root delayDuration={delayDuration}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          align={align}
          sideOffset={6}
          className={cn(
            'bg-surface-inverse text-on-inverse shadow-elevated z-modal max-w-tooltip rounded-[var(--radius-overlay)] px-1.5 py-1 text-xs font-normal',
            className,
          )}
        >
          {content}
          <TooltipPrimitive.Arrow className="fill-surface-inverse" />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
