'use client';

import type { ReactNode } from 'react';

import { filterChipClasses } from '@/components/ui/filter-chip-variants';
import { cn } from '@/lib/utils';

/** A compact toggle for filtering a data set without changing views. */
export function FilterChip({
  active,
  onClick,
  count,
  children,
}: Readonly<{
  active: boolean;
  onClick: () => void;
  count?: number;
  children: ReactNode;
}>) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={filterChipClasses(active)}
    >
      {children}
      {typeof count === 'number' ? (
        <span className={cn('mono text-2xs', active ? 'text-accent-text' : 'text-muted')}>
          {count}
        </span>
      ) : null}
    </button>
  );
}
