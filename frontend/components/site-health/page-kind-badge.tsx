'use client';

import { Badge } from '@/components/ui/badge';
import { pageKindLabel } from '@/lib/site-health/page-kinds';
import { PLACEHOLDER } from '@/lib/site-health/status';

/**
 * The page-kind chip (site-health v2 P1) rendered on page rows (pages +
 * inventory), affected-URL rows, and the per-URL detail header. Reuses the
 * design-system neutral `Badge` — no new colour family. An unclassified page
 * (no completed analysis yet, or a projection that does not carry the field)
 * renders the `Not measured` placeholder, never a guessed type.
 */
export function PageKindBadge({ pageKind }: Readonly<{ pageKind: string | null | undefined }>) {
  if (!pageKind) {
    return <span className="text-muted">{PLACEHOLDER}</span>;
  }
  return <Badge>{pageKindLabel(pageKind)}</Badge>;
}
