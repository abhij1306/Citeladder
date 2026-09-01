'use client';

import type { ReactNode } from 'react';
import * as RadioGroupPrimitive from '@radix-ui/react-radio-group';
import { Check } from 'lucide-react';

import { cn } from '@/lib/utils';
import { Tooltip } from './tooltip';

export type RadioOption<T extends string> = {
  value: T;
  label: ReactNode;
  disabled?: boolean;
  description?: ReactNode;
  groupLabel?: string;
};

export function RadioGroup<T extends string>({
  value,
  onValueChange,
  options,
  ariaLabel,
  className,
  variant = 'standard',
}: Readonly<{
  value: T;
  onValueChange: (value: T) => void;
  options: readonly RadioOption<T>[];
  ariaLabel: string;
  className?: string;
  variant?: 'standard' | 'chip';
}>) {
  return (
    <RadioGroupPrimitive.Root
      value={value}
      onValueChange={(next) => onValueChange(next as T)}
      aria-label={ariaLabel}
      data-radio-variant={variant}
      className={cn(
        variant === 'chip' ? 'flex flex-wrap items-center gap-1.5' : 'grid gap-2',
        className,
      )}
    >
      {variant === 'chip' ? (
        <RadioChips options={options} />
      ) : (
        options.map((option) => (
          <label key={option.value} className="inline-flex items-center gap-2 text-sm">
            <RadioGroupPrimitive.Item
              value={option.value}
              disabled={option.disabled}
              className="focus-ring border-border-bold bg-input data-[state=checked]:border-accent grid size-4 shrink-0 place-items-center rounded-full border disabled:opacity-50"
            >
              <RadioGroupPrimitive.Indicator>
                <span className="bg-accent block size-2 rounded-full" />
              </RadioGroupPrimitive.Indicator>
            </RadioGroupPrimitive.Item>
            <span className={cn(option.disabled && 'opacity-50')}>{option.label}</span>
          </label>
        ))
      )}
    </RadioGroupPrimitive.Root>
  );
}

function RadioChips<T extends string>({
  options,
}: Readonly<{ options: readonly RadioOption<T>[] }>) {
  const grouped = options.some((option) => option.groupLabel);
  if (!grouped) return options.map((option) => <RadioChip key={option.value} option={option} />);

  const groups = new Map<string, RadioOption<T>[]>();
  for (const option of options) {
    const label = option.groupLabel ?? '';
    groups.set(label, [...(groups.get(label) ?? []), option]);
  }
  return [...groups.entries()].map(([label, groupOptions]) => (
    <div key={label} className="flex w-full flex-wrap items-center gap-2">
      <span className="text-muted w-20 shrink-0 text-xs font-medium">{label}</span>
      {groupOptions.map((option) => (
        <RadioChip key={option.value} option={option} />
      ))}
    </div>
  ));
}

function RadioChip<T extends string>({ option }: Readonly<{ option: RadioOption<T> }>) {
  const item = (
    <RadioGroupPrimitive.Item
      value={option.value}
      disabled={option.disabled}
      className="focus-ring border-border bg-panel text-secondary hover:border-border-strong hover:text-foreground data-[state=checked]:border-accent-border data-[state=checked]:bg-accent-soft data-[state=checked]:text-accent-text ease-standard inline-flex h-[var(--control-height-sm)] items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-[border-color,background-color,color] duration-[250ms] disabled:cursor-not-allowed disabled:opacity-50"
    >
      <span aria-hidden className="grid size-3.5 shrink-0 place-items-center">
        <RadioGroupPrimitive.Indicator>
          <Check className="size-3.5" strokeWidth={2.5} />
        </RadioGroupPrimitive.Indicator>
      </span>
      <span>{option.label}</span>
    </RadioGroupPrimitive.Item>
  );
  return option.description ? <Tooltip content={option.description}>{item}</Tooltip> : item;
}
