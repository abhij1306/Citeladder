'use client';

import type { InputHTMLAttributes } from 'react';
import { LoaderCircle, Search, X } from 'lucide-react';

import { Input } from './input';
import { Pressable } from './pressable';

export type SearchFieldProps = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  'type' | 'value' | 'onChange' | 'size'
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
    <Input
      {...props}
      type="search"
      value={value}
      onChange={(event) => onValueChange(event.target.value)}
      aria-label={ariaLabel}
      aria-busy={pending || undefined}
      containerClassName={className}
      className="[appearance:textfield] [&::-webkit-search-cancel-button]:hidden"
      startContent={
        pending ? (
          <LoaderCircle className="text-muted size-4 shrink-0 animate-spin" aria-hidden />
        ) : (
          <Search className="text-muted size-4 shrink-0" aria-hidden />
        )
      }
      endContent={
        value ? (
          <Pressable
            className="text-muted hover:bg-well hover:text-foreground -mr-1 grid size-6 w-6 place-items-center rounded-[var(--radius-control)]"
            disabled={props.disabled}
            onClick={() => (onClear ? onClear() : onValueChange(''))}
            aria-label="Clear search"
          >
            <X className="size-3.5" aria-hidden />
          </Pressable>
        ) : null
      }
    />
  );
}
