'use client';

import type { ReactNode } from 'react';
import * as CheckboxPrimitive from '@radix-ui/react-checkbox';
import { Check, Minus } from 'lucide-react';

import { cn } from '@/lib/utils';

type AccessibleCheckbox =
  | { label: ReactNode; 'aria-label'?: never }
  | { label?: never; 'aria-label': string };

export type CheckboxProps = AccessibleCheckbox & {
  checked: boolean | 'indeterminate';
  onCheckedChange: (checked: boolean | 'indeterminate') => void;
  disabled?: boolean;
  className?: string;
  id?: string;
  name?: string;
  required?: boolean;
};

export function Checkbox({
  checked,
  onCheckedChange,
  label,
  disabled,
  className,
  id,
  name,
  required,
  'aria-label': ariaLabel,
}: Readonly<CheckboxProps>) {
  const control = (
    <CheckboxPrimitive.Root
      id={id}
      name={name}
      required={required}
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-label={ariaLabel}
      className="focus-ring group grid min-h-[var(--control-height)] min-w-[var(--control-height)] shrink-0 place-items-center rounded-[var(--radius-control)] disabled:cursor-not-allowed disabled:opacity-60"
    >
      <span className="border-input bg-input-bg group-hover:border-border-bold group-data-[state=checked]:border-accent group-data-[state=checked]:bg-accent group-data-[state=indeterminate]:border-accent group-data-[state=indeterminate]:bg-accent text-accent-fg grid size-4 place-items-center rounded-[var(--radius-control)] border transition-[background-color,border-color] duration-[var(--transition-fast)]">
        <CheckboxPrimitive.Indicator>
          {checked === 'indeterminate' ? (
            <Minus className="size-3" aria-hidden />
          ) : (
            <Check className="size-3" aria-hidden />
          )}
        </CheckboxPrimitive.Indicator>
      </span>
    </CheckboxPrimitive.Root>
  );

  if (label === undefined) return <span className={className}>{control}</span>;

  return (
    <label className={cn('inline-flex items-center gap-2 text-sm', className)}>
      {control}
      <span className={cn(disabled && 'opacity-60')}>{label}</span>
    </label>
  );
}
