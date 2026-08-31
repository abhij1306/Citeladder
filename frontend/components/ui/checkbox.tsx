'use client';

import type { ReactNode } from 'react';
import * as CheckboxPrimitive from '@radix-ui/react-checkbox';
import { Check, Minus } from 'lucide-react';

import { cn } from '@/lib/utils';

export function Checkbox({
  checked,
  onCheckedChange,
  label,
  disabled,
  className,
}: Readonly<{
  checked: boolean | 'indeterminate';
  onCheckedChange: (checked: boolean | 'indeterminate') => void;
  label: ReactNode;
  disabled?: boolean;
  className?: string;
}>) {
  return (
    <label
      className={cn('inline-flex items-center gap-2 text-sm', disabled && 'opacity-60', className)}
    >
      <CheckboxPrimitive.Root
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        className="focus-ring border-input bg-input-bg data-[state=checked]:border-accent data-[state=checked]:bg-accent data-[state=indeterminate]:border-accent data-[state=indeterminate]:bg-accent text-accent-fg grid size-4 shrink-0 place-items-center rounded-[var(--radius-control)] border disabled:cursor-not-allowed"
      >
        <CheckboxPrimitive.Indicator>
          {checked === 'indeterminate' ? (
            <Minus className="size-3" aria-hidden />
          ) : (
            <Check className="size-3" aria-hidden />
          )}
        </CheckboxPrimitive.Indicator>
      </CheckboxPrimitive.Root>
      <span>{label}</span>
    </label>
  );
}
