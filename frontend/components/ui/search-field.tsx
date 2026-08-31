'use client';

import type { InputHTMLAttributes } from 'react';
import { LoaderCircle, Search, X } from 'lucide-react';

import { cn } from '@/lib/utils';
import { Pressable } from './pressable';

export type SearchFieldProps = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  'type' | 'value' | 'onChange'
> & {
  value: string;
  onValueChange: (value: string) => void;
  pending?: boolean;
  onClear?: () => void;
};

export function SearchField({
  value,
  onValueChange,
  pending = false,
  onClear,
  className,
  'aria-label': ariaLabel = 'Search',
  ...props
}: Readonly<SearchFieldProps>) {
  return (
    <div
      className={cn(
        'border-input bg-input-bg focus-within:border-accent focus-within:shadow-[var(--focus-ring)] flex h-[var(--control-height)] items-center gap-2 rounded-[var(--radius-control)] border px-2.5 transition-[border-color,box-shadow,background-color]',
        className,
      )}
    >
      {pending ? (
        <LoaderCircle className="text-muted size-4 shrink-0 animate-spin" aria-hidden />
      ) : (
        <Search className="text-muted size-4 shrink-0" aria-hidden />
      )}
      <input
        type="search"
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
        aria-label={ariaLabel}
        aria-busy={pending || undefined}
        className="placeholder:text-subtle min-w-0 flex-1 [appearance:textfield] bg-transparent text-sm outline-none [&::-webkit-search-cancel-button]:hidden"
        {...props}
      />
      {value ? (
        <Pressable
          className="text-muted hover:bg-well hover:text-foreground -mr-1 grid size-6 w-6 place-items-center rounded-[var(--radius-control)]"
          onClick={() => (onClear ? onClear() : onValueChange(''))}
          aria-label="Clear search"
        >
          <X className="size-3.5" aria-hidden />
        </Pressable>
      ) : null}
    </div>
  );
}
