'use client';

import { ChevronDown } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dropdown,
  DropdownCheckboxItem,
  DropdownContent,
  DropdownTrigger,
} from '@/components/ui/dropdown';
import type { CommerceTarget } from '@/lib/api/schemas/commerce-suite';

export type TargetOption = { label: string; target: CommerceTarget };

export const targetKey = (target: CommerceTarget) => `${target.kind}:${target.id}`;

function summary(selected: TargetOption[], placeholder: string): string {
  if (!selected.length) return placeholder;
  if (selected.length === 1) return selected[0].label;
  return `${selected.length} targets selected`;
}

/**
 * Pick one or many Commerce targets in a single control.
 *
 * The panels used a single-choice select, so running discovery or generation
 * across a catalog meant re-picking and re-clicking once per category — the
 * backend has always accepted a list of targets. This is the Radix menu rather
 * than a native `<select multiple>`, which renders as an unusable scrolling
 * multi-row box and has no accessible "select all".
 */
export function TargetMultiSelect({
  label,
  options,
  selectedKeys,
  onChange,
  placeholder = 'Select targets',
}: Readonly<{
  label: string;
  options: TargetOption[];
  selectedKeys: string[];
  onChange: (keys: string[]) => void;
  placeholder?: string;
}>) {
  const chosen = new Set(selectedKeys);
  const selected = options.filter((option) => chosen.has(targetKey(option.target)));
  const allSelected = options.length > 0 && selected.length === options.length;
  const toggle = (key: string) =>
    onChange(
      chosen.has(key) ? selectedKeys.filter((value) => value !== key) : [...selectedKeys, key],
    );
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <Button variant="secondary" aria-label={label} className="min-w-64 justify-between">
          <span className="truncate">{summary(selected, placeholder)}</span>
          <ChevronDown className="text-muted size-4 shrink-0" aria-hidden />
        </Button>
      </DropdownTrigger>
      <DropdownContent className="max-h-80 w-72 overflow-y-auto">
        <DropdownCheckboxItem
          checked={allSelected}
          onCheckedChange={() =>
            onChange(allSelected ? [] : options.map((option) => targetKey(option.target)))
          }
          onSelect={(event) => event.preventDefault()}
        >
          Select all
        </DropdownCheckboxItem>
        {options.map((option) => {
          const key = targetKey(option.target);
          return (
            <DropdownCheckboxItem
              key={key}
              checked={chosen.has(key)}
              onCheckedChange={() => toggle(key)}
              onSelect={(event) => event.preventDefault()}
            >
              {option.label}
            </DropdownCheckboxItem>
          );
        })}
      </DropdownContent>
    </Dropdown>
  );
}
