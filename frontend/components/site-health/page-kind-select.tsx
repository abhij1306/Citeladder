'use client';

import { ChevronDown } from 'lucide-react';

import { inputClasses } from '@/components/ui/input';
import { PAGE_KINDS, pageKindLabel } from '@/lib/site-health/page-kinds';
import { cn } from '@/lib/utils';

/**
 * The page-kind filter control (site-health v2 P1) shared by the pages,
 * inventory, and issues list screens. A native `<select>` on the shared
 * `inputClasses` control treatment (the same pattern as the Topics narrow
 * selector) — the empty option clears the filter (all page kinds).
 */
export function PageKindSelect({
  value,
  onChange,
}: Readonly<{ value: string; onChange: (value: string) => void }>) {
  return (
    <div className="relative w-44">
      <select
        aria-label="Filter by page kind"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={cn(inputClasses, 'appearance-none pe-8')}
      >
        <option value="">All page kinds</option>
        {PAGE_KINDS.map((pageKind) => (
          <option key={pageKind} value={pageKind}>
            {pageKindLabel(pageKind)}
          </option>
        ))}
      </select>
      <ChevronDown
        className="text-muted pointer-events-none absolute end-2 top-1/2 size-4 -translate-y-1/2"
        aria-hidden
      />
    </div>
  );
}
