'use client';

import type { ReactNode } from 'react';
import * as RadioGroupPrimitive from '@radix-ui/react-radio-group';

import { cn } from '@/lib/utils';

export type RadioOption<T extends string> = { value: T; label: ReactNode; disabled?: boolean };

export function RadioGroup<T extends string>({
  value,
  onValueChange,
  options,
  ariaLabel,
  className,
}: Readonly<{
  value: T;
  onValueChange: (value: T) => void;
  options: readonly RadioOption<T>[];
  ariaLabel: string;
  className?: string;
}>) {
  return (
    <RadioGroupPrimitive.Root
      value={value}
      onValueChange={(next) => onValueChange(next as T)}
      aria-label={ariaLabel}
      className={cn('grid gap-2', className)}
    >
      {options.map((option) => (
        <label key={option.value} className="inline-flex items-center gap-2 text-sm">
          <RadioGroupPrimitive.Item
            value={option.value}
            disabled={option.disabled}
            className="focus-ring border-input bg-input-bg data-[state=checked]:border-accent grid size-4 shrink-0 place-items-center rounded-full border disabled:opacity-50"
          >
            <RadioGroupPrimitive.Indicator className="bg-accent size-2 rounded-full" />
          </RadioGroupPrimitive.Item>
          <span className={cn(option.disabled && 'opacity-50')}>{option.label}</span>
        </label>
      ))}
    </RadioGroupPrimitive.Root>
  );
}
