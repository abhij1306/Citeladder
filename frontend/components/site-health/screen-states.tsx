'use client';

import type { ReactNode } from 'react';

import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

/**
 * Stateless presentational pieces of the Site Health screen (header + loading
 * skeleton). All behavior stays in `site-health-screen.tsx`; these only render
 * what they are handed. The empty / terminal lifecycle states are in-section
 * content of the canonical layout (`StatusStrip` / `InventorySection`), not
 * separate cards — the screen never swaps panels.
 */

export function ScreenHeader({ actions }: Readonly<{ actions?: ReactNode }>) {
  if (!actions) return null;
  return (
    <div className="relative z-10 flex flex-wrap items-center justify-end gap-2">{actions}</div>
  );
}

export function ScreenSkeleton({ label = 'Loading Site Health…' }: Readonly<{ label?: string }>) {
  return (
    <div
      className="grid gap-[var(--workspace-gap)]"
      aria-busy="true"
      data-testid="site-health-skeleton"
    >
      <div
        // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- output cannot contain the block skeleton used by this loading live region.
        role="status"
        className="flex min-h-8 items-center gap-3"
      >
        <Skeleton className="size-2 shrink-0 rounded-full" />
        <p className="text-secondary text-sm font-medium">{label}</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3" aria-hidden>
        {Array.from({ length: 3 }, (_, index) => (
          <Card key={index}>
            <CardContent className="flex items-center gap-4">
              <Skeleton className="size-score-ring shrink-0 rounded-full" />
              <div className="grid flex-1 gap-2">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-5 w-20" />
                <Skeleton className="h-3 w-full max-w-44" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardContent className="grid gap-[var(--workspace-gap)]" aria-hidden>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="grid gap-2">
              <Skeleton className="h-5 w-36" />
              <Skeleton className="h-3 w-64 max-w-full" />
            </div>
            <Skeleton className="h-8 w-28 rounded-full" />
          </div>
          <div className="border-border-subtle grid gap-3 border-t pt-4">
            {Array.from({ length: 4 }, (_, index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
