'use client';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { UnavailableValue } from '@/components/ui/unavailable-value';
import type { InventoryRow } from '@/lib/api/types';
import { PageKindBadge } from '@/components/site-health/page-kind-badge';
import { pageDisplayTitle } from '@/lib/site-health/status';

/** The cursor-paginated inventory rows with per-row monitored checkboxes. */
export function InventoryTable({
  rows,
  isStaged,
  disabled,
  onToggle,
}: Readonly<{
  rows: readonly InventoryRow[];
  isStaged: (siteUrlId: string) => boolean;
  disabled: boolean;
  onToggle: (siteUrlId: string) => void;
}>) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-10" />
          <TableHead>Page URL</TableHead>
          <TableHead>Page Kind</TableHead>
          <TableHead>Content Type</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.site_url_id}>
            <TableCell>
              <input
                type="checkbox"
                checked={isStaged(row.site_url_id)}
                disabled={disabled}
                aria-label={`Monitor ${row.display_url}`}
                onChange={() => onToggle(row.site_url_id)}
                className="focus-ring accent-accent size-4 shrink-0"
              />
            </TableCell>
            <TableCell>
              {/* Clamped on the inner box (a `<td>` max-width is advisory under
                  `table-layout: auto`): a URL is one unbreakable token and
                  would otherwise size the column to its full length. */}
              <span className="flex max-w-[32rem] min-w-0 flex-col">
                <span
                  className="text-foreground truncate font-medium"
                  title={pageDisplayTitle(row.title, row.display_url)}
                >
                  {pageDisplayTitle(row.title, row.display_url)}
                </span>
                <span className="mono text-2xs text-muted truncate" title={row.display_url}>
                  {row.display_url}
                </span>
              </span>
            </TableCell>
            <TableCell>
              <PageKindBadge pageKind={row.page_kind} />
            </TableCell>
            <TableCell className="text-secondary text-xs">
              {row.content_type ?? <UnavailableValue state="unknown" />}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
