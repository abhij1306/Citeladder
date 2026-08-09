'use client';

import * as DropdownPrimitive from '@radix-ui/react-dropdown-menu';
import { Check } from 'lucide-react';
import type { ComponentPropsWithoutRef, ReactNode } from 'react';

import { eyebrowClasses } from '@/components/ui/eyebrow';
import { menuItemVariants, menuPanelClasses } from '@/components/ui/menu-variants';
import { cn } from '@/lib/utils';

/**
 * Dropdown (§8) — Radix menu. Surface = bg-elevated, border,
 * shadow-elevated, and the shared menu radius.
 * Re-exports the Radix parts with token-styled Content / Item defaults.
 */
export const Dropdown = DropdownPrimitive.Root;
export const DropdownTrigger = DropdownPrimitive.Trigger;
export const DropdownSeparator = DropdownPrimitive.Separator;
export const DropdownRadioGroup = DropdownPrimitive.RadioGroup;

export function DropdownContent({
  className,
  align = 'start',
  sideOffset = 4,
  children,
  ...props
}: Readonly<ComponentPropsWithoutRef<typeof DropdownPrimitive.Content>>) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.Content
        align={align}
        sideOffset={sideOffset}
        className={cn(menuPanelClasses, 'min-w-40', className)}
        {...props}
      >
        {children}
      </DropdownPrimitive.Content>
    </DropdownPrimitive.Portal>
  );
}

export function DropdownItem({
  className,
  children,
  ...props
}: Readonly<ComponentPropsWithoutRef<typeof DropdownPrimitive.Item>>) {
  return (
    <DropdownPrimitive.Item className={cn(menuItemVariants(), className)} {...props}>
      {children}
    </DropdownPrimitive.Item>
  );
}

export function DropdownCheckboxItem({
  className,
  children,
  ...props
}: Readonly<ComponentPropsWithoutRef<typeof DropdownPrimitive.CheckboxItem>>) {
  return (
    <DropdownPrimitive.CheckboxItem
      className={cn(
        // `relative` makes each row the containing block for its own absolutely
        // positioned indicator below — without it every checkmark resolves
        // against a distant ancestor and they all stack in one spot.
        menuItemVariants({ inset: true }),
        className,
      )}
      {...props}
    >
      <span className="absolute start-2 flex size-4 items-center justify-center">
        <DropdownPrimitive.ItemIndicator>
          <Check className="text-accent size-4" aria-hidden />
        </DropdownPrimitive.ItemIndicator>
      </span>
      {children}
    </DropdownPrimitive.CheckboxItem>
  );
}

export function DropdownRadioItem({
  className,
  children,
  ...props
}: Readonly<ComponentPropsWithoutRef<typeof DropdownPrimitive.RadioItem>>) {
  return (
    <DropdownPrimitive.RadioItem
      className={cn(menuItemVariants({ inset: true }), className)}
      {...props}
    >
      <span className="absolute start-2 flex size-4 items-center justify-center">
        <DropdownPrimitive.ItemIndicator>
          <Check className="text-accent size-4" aria-hidden />
        </DropdownPrimitive.ItemIndicator>
      </span>
      {children}
    </DropdownPrimitive.RadioItem>
  );
}

export function DropdownLabel({
  className,
  children,
}: Readonly<{ className?: string; children: ReactNode }>) {
  return (
    <DropdownPrimitive.Label className={cn(eyebrowClasses, 'px-2 py-1', className)}>
      {children}
    </DropdownPrimitive.Label>
  );
}
