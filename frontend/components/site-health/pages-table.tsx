'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { scoreTextClass } from '@/components/ui/score-band';
import { cn } from '@/lib/utils';
import type { PagesSort } from '@/lib/api/site-health';
import type { PageSummary } from '@/lib/api/types';
import { PageKindBadge } from '@/components/site-health/page-kind-badge';
import {
  PLACEHOLDER,
  formatAudited,
  formatIssueCount,
  formatScore,
  pageDisplayTitle,
  pageStatusBadgeValue,
  statusLabel,
} from '@/lib/site-health/status';

/**
 * Analyzed-pages table (Slice 7, mockups 712 + 713).
 *
 * Renders one row per analyzed page: URL (+ path), the page-kind badge (v2
 * P1), a per-page analysis status badge (queued/running/completed/error/
 * blocked), issue count, Web Fundamentals / AEO scores, the crawl's internal-link
 * metrics, last audited, and a View action. Missing / not-yet-analysed scores and
 * unmeasured link metrics render the `Not measured` placeholder — never a
 * fabricated zero (an error/blocked row shows `Not measured`, not 0; a page with no
 * metric row is unmeasured, not unlinked). The whole row is clickable and navigates
 * to the Slice 8 per-URL detail route (`/site/crawls/[crawlId]/pages/[siteUrlId]`);
 * the View link remains as the keyboard/screen-reader affordance.
 *
 * Sorting is SERVER-SIDE and keyset-paged: each link column asks the backend to
 * reorder the whole result set, never the current page window. Each sort has one
 * meaningful direction (most-linked first, shallowest first), so a header selects
 * a sort rather than toggling one.
 */

const LINK_COLUMNS: ReadonlyArray<{
  sort: Exclude<PagesSort, 'url'>;
  label: string;
  descending: boolean;
  value: (page: PageSummary) => number | null;
}> = [
  {
    sort: 'inbound',
    label: 'Inbound',
    descending: true,
    value: (page) => page.inbound_count,
  },
];

function SortableHead({
  label,
  active,
  descending,
  onSort,
}: Readonly<{ label: string; active: boolean; descending: boolean; onSort: () => void }>) {
  const Icon = active ? (descending ? ArrowDown : ArrowUp) : ArrowUpDown;
  return (
    <TableHead numeric aria-sort={active ? (descending ? 'descending' : 'ascending') : undefined}>
      <button
        type="button"
        onClick={onSort}
        className={cn(
          'inline-flex items-center gap-1',
          active ? 'text-accent-text' : 'hover:text-foreground',
        )}
      >
        {label}
        <Icon className={cn('size-3', !active && 'text-subtle')} aria-hidden />
      </button>
    </TableHead>
  );
}

export function PagesTable({
  pages,
  crawlId,
  sort = 'url',
  onSortChange,
}: Readonly<{
  pages: PageSummary[];
  crawlId: string;
  sort?: PagesSort;
  /** Omitted where the table is read-only; the link headers then render plain. */
  onSortChange?: (sort: PagesSort) => void;
}>) {
  const router = useRouter();
  const openPage = (siteUrlId: string) => {
    const page = pages.find((row) => row.site_url_id === siteUrlId);
    router.push(`/site/crawls/${page?.crawl_id ?? crawlId}/pages/${siteUrlId}`);
  };
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead numeric className="w-10">
            #
          </TableHead>
          <TableHead>Page URL</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Status</TableHead>
          <TableHead numeric>Issues</TableHead>
          <TableHead numeric>Technical Integrity</TableHead>
          <TableHead numeric>AEO Readiness</TableHead>
          <TableHead numeric>AEO Coverage</TableHead>
          {LINK_COLUMNS.map((column) =>
            onSortChange ? (
              <SortableHead
                key={column.sort}
                label={column.label}
                active={sort === column.sort}
                descending={column.descending}
                onSort={() => onSortChange(sort === column.sort ? 'url' : column.sort)}
              />
            ) : (
              <TableHead key={column.sort} numeric>
                {column.label}
              </TableHead>
            ),
          )}
          <TableHead>Main-content indexable</TableHead>
          <TableHead>Last Audit</TableHead>
          <TableHead className="w-16" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {pages.map((page, index) => (
          <TableRow
            key={page.site_url_id}
            // The row is the primary affordance, so it has to be reachable and
            // operable from the keyboard too — the trailing `View` link is a
            // shortcut, not a substitute for the row.
            tabIndex={0}
            // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- A table row cannot be wrapped by an anchor; the row implements the link keyboard contract.
            role="link"
            aria-label={pageDisplayTitle(page.title, page.display_url)}
            onClick={() => openPage(page.site_url_id)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter' && event.key !== ' ') return;
              if (event.target !== event.currentTarget) return;
              event.preventDefault();
              openPage(page.site_url_id);
            }}
            className="focus-visible:ring-accent/60 cursor-pointer focus-visible:ring-2 focus-visible:outline-none"
          >
            <TableCell numeric className="mono text-muted text-xs">
              {index + 1}
            </TableCell>
            {/* A URL is one unbreakable token, so an untruncated cell takes its
                full max-content width and shoves every following column off
                screen — one tracking-parameter URL was enough to make the
                table unreadable. Both lines are clamped to a fixed column and
                carry the full value as a title tooltip. */}
            {/* The clamp lives on the inner box, not the `<td>`: under the
                default `table-layout: auto` browsers treat `max-width` on a
                cell as advisory and size the column to content anyway. */}
            <TableCell>
              <span className="flex max-w-[26rem] min-w-0 flex-col">
                <span
                  className="text-foreground truncate font-medium"
                  title={pageDisplayTitle(page.title, page.display_url)}
                >
                  {pageDisplayTitle(page.title, page.display_url)}
                </span>
                <span className="mono text-2xs text-muted truncate" title={page.display_url}>
                  {page.display_url}
                </span>
              </span>
            </TableCell>
            <TableCell>
              <PageKindBadge pageKind={page.page_kind} />
            </TableCell>
            <TableCell>
              <Badge variant="status" value={pageStatusBadgeValue(page.analysis_status)}>
                {statusLabel(page.analysis_status)}
              </Badge>
            </TableCell>
            <TableCell numeric className="mono text-danger-text">
              {formatIssueCount(page.issue_count)}
            </TableCell>
            <TableCell
              numeric
              className={cn('mono font-medium', scoreTextClass(page.technical_integrity_score))}
            >
              {page.technical_integrity_state === 'measured'
                ? formatScore(page.technical_integrity_score)
                : PLACEHOLDER}
            </TableCell>
            <TableCell
              numeric
              className={cn('mono font-medium', scoreTextClass(page.aeo_readiness_score))}
            >
              {page.aeo_measurement_state === 'measured'
                ? formatScore(page.aeo_readiness_score)
                : PLACEHOLDER}
            </TableCell>
            <TableCell numeric className="mono font-medium">
              {page.aeo_measurement_coverage === null
                ? PLACEHOLDER
                : `${Math.round(page.aeo_measurement_coverage * 100)}%`}
            </TableCell>
            {LINK_COLUMNS.map((column) => {
              const value = column.value(page);
              return (
                <TableCell
                  key={column.sort}
                  numeric
                  className={cn('mono', value === null ? 'text-muted text-xs' : 'text-secondary')}
                >
                  {value === null ? PLACEHOLDER : value}
                </TableCell>
              );
            })}
            <TableCell className="text-secondary text-xs">
              {page.main_content_indexable === null
                ? PLACEHOLDER
                : page.main_content_indexable
                  ? 'Indexable'
                  : 'Blocked'}
            </TableCell>
            <TableCell className="text-secondary text-xs whitespace-nowrap">
              {formatAudited(page.last_audited)}
            </TableCell>
            <TableCell>
              <Link
                href={`/site/crawls/${page.crawl_id}/pages/${page.site_url_id}`}
                onClick={(event) => event.stopPropagation()}
                className="text-accent-text text-xs font-medium hover:underline"
              >
                View
              </Link>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
