'use client';

import { Badge } from '@/components/ui/badge';
import { pageKindLabel } from '@/lib/site-health/page-kinds';
import { PLACEHOLDER } from '@/lib/site-health/status';
import { cn } from '@/lib/utils';

/**
 * The page-kind chip (site-health v2 P1) rendered on page rows (pages +
 * inventory), affected-URL rows, and the per-URL detail header. Reuses the
 * design-system neutral `Badge` — no new colour family. An unclassified page
 * (no completed analysis yet, or a projection that does not carry the field)
 * renders the `Not measured` placeholder, never a guessed type.
 *
 * `className` exists so the tables where the chip is the row's primary label
 * (Scores by Page Kind, Architecture → Page kinds) can lift it to `text-xs`;
 * everywhere else it stays at the badge's default `text-2xs`.
 */
export function PageKindBadge({
  pageKind,
  className,
}: Readonly<{ pageKind: string | null | undefined; className?: string }>) {
  if (!pageKind) {
    return <span className={cn('text-muted', className)}>{PLACEHOLDER}</span>;
  }
  return <Badge className={className}>{pageKindLabel(pageKind)}</Badge>;
}
