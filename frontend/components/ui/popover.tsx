'use client';

import type { ComponentPropsWithoutRef } from 'react';
import * as PopoverPrimitive from '@radix-ui/react-popover';

import { cn } from '@/lib/utils';

export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;

export function PopoverContent({
  className,
  sideOffset = 6,
  collisionPadding = 8,
  ...props
}: Readonly<ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        sideOffset={sideOffset}
        collisionPadding={collisionPadding}
        className={cn(
          'menu-panel border-border bg-elevated z-[var(--z-index-overlay)] rounded-[var(--radius-overlay)] border p-[var(--card-padding)] shadow-elevated outline-none',
          className,
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  );
}
