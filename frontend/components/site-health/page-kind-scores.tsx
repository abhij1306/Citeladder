'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { CursorPager } from '@/components/ui/cursor-pager';
import { Skeleton } from '@/components/ui/skeleton';
import { scoreTextClass } from '@/components/ui/score-band';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Label } from '@/components/ui/typography';
import { PageKindBadge } from '@/components/site-health/page-kind-badge';
import { siteHealthQueries } from '@/lib/api/site-health';
import type { PageKind, SiteCrawl, SiteHealthDashboard } from '@/lib/api/types';
import { byPageKindRows } from '@/lib/site-health/page-kinds';
import { useCursorStack } from '@/lib/site-health/use-cursor-stack';
import {
  formatScore,
  PAGE_LIMIT,
  pageStatusBadgeValue,
  statusLabel,
} from '@/lib/site-health/status';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

/**
 * Dashboard per-page-kind score breakdown (site-health v2 P1).
 *
 * Renders `score_summary.by_page_kind` — one row per classified page kind
 * with its analyzed count and mean Technical/AEO/overall scores. Like the
 * score cards, the panel is data-driven: it appears once a score summary
 * exists (a mid-run projection included) and follows the same
 * dashboard-then-crawl fallback. An empty breakdown means analysis has not
 * classified any page yet; missing mean scores render `—`, never a
 * fabricated zero.
 */
export function PageKindScores({
  crawl,
  dashboard,
  selectedUrlIds = new Set<string>(),
  onSelectionChange,
  onReanalyze,
  reanalyzePending,
}: Readonly<{
  crawl: SiteCrawl | null;
  dashboard: SiteHealthDashboard | undefined;
  selectedUrlIds?: ReadonlySet<string>;
  onSelectionChange?: (ids: Set<string>) => void;
  onReanalyze?: (siteUrlIds: string[]) => void;
  reanalyzePending?: boolean;
}>) {
  const [expanded, setExpanded] = useState<PageKind | null>(null);
  const summary = dashboard?.score_summary ?? crawl?.score_summary ?? null;
  if (summary === null) return null;

  const rows = byPageKindRows(summary.by_page_kind);

  return (
    <Card data-testid="page-kind-scores">
      <CardContent className="grid gap-3">
        <div className="grid gap-0.5">
          <Label>Scores by Page Kind</Label>
          <span className="text-secondary text-sm">
            Mean scores across the analyzed pages of each type.
          </span>
        </div>
        {rows.length === 0 ? (
          <p className="text-secondary text-sm">
            Per-page-kind scores appear once the analysis classifies your pages.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Page Kind</TableHead>
                <TableHead numeric>Analyzed</TableHead>
                <TableHead numeric>Web Fundamentals</TableHead>
                <TableHead numeric>AEO</TableHead>
                <TableHead numeric>Overall</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => {
                const open = expanded === row.page_kind;
                return (
                  <PageKindAccordionRow
                    key={row.page_kind}
                    crawlId={crawl?.id ?? ''}
                    row={row}
                    open={open}
                    onToggle={() => setExpanded(open ? null : (row.page_kind as PageKind))}
                    selectedUrlIds={selectedUrlIds}
                    onSelectionChange={onSelectionChange}
                    onReanalyze={onReanalyze}
                    reanalyzePending={reanalyzePending}
                  />
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

type ScoreRow = ReturnType<typeof byPageKindRows>[number];

function PageKindAccordionRow({
  crawlId,
  row,
  open,
  onToggle,
  selectedUrlIds,
  onSelectionChange,
  onReanalyze,
  reanalyzePending,
}: Readonly<{
  crawlId: string;
  row: ScoreRow;
  open: boolean;
  onToggle: () => void;
  selectedUrlIds: ReadonlySet<string>;
  onSelectionChange?: (ids: Set<string>) => void;
  onReanalyze?: (siteUrlIds: string[]) => void;
  reanalyzePending?: boolean;
}>) {
  return (
    <>
      <TableRow>
        <TableCell>
          <button
            type="button"
            className="focus-ring flex items-center gap-2 rounded-sm"
            aria-expanded={open}
            disabled={!crawlId}
            onClick={onToggle}
          >
            <ChevronDown
              aria-hidden="true"
              className={cn('size-4 transition-transform', open && 'rotate-180')}
            />
            <PageKindBadge pageKind={row.page_kind} />
          </button>
        </TableCell>
        <TableCell numeric className="mono text-secondary">
          {row.analyzed_count}
        </TableCell>
        <TableCell numeric className={cn('mono font-medium', scoreTextClass(row.technical_score))}>
          {formatScore(row.technical_score)}
        </TableCell>
        <TableCell numeric className={cn('mono font-medium', scoreTextClass(row.aeo_score))}>
          {formatScore(row.aeo_score)}
        </TableCell>
        <TableCell numeric className={cn('mono font-medium', scoreTextClass(row.overall_score))}>
          {formatScore(row.overall_score)}
        </TableCell>
      </TableRow>
      {open ? (
        <TableRow>
          <TableCell colSpan={5} className="bg-subtle p-0">
            <PageKindDetails
              crawlId={crawlId}
              pageKind={row.page_kind}
              selectedUrlIds={selectedUrlIds}
              onSelectionChange={onSelectionChange}
              onReanalyze={onReanalyze}
              reanalyzePending={reanalyzePending}
            />
          </TableCell>
        </TableRow>
      ) : null}
    </>
  );
}

function PageKindDetails({
  crawlId,
  pageKind,
  selectedUrlIds,
  onSelectionChange,
  onReanalyze,
  reanalyzePending,
}: Readonly<{
  crawlId: string;
  pageKind: string;
  selectedUrlIds: ReadonlySet<string>;
  onSelectionChange?: (ids: Set<string>) => void;
  onReanalyze?: (siteUrlIds: string[]) => void;
  reanalyzePending?: boolean;
}>) {
  const pager = useCursorStack();
  const pagesQuery = useQuery(
    siteHealthQueries.pages(crawlId, {
      page_kind: pageKind,
      cursor: pager.cursor,
      limit: PAGE_LIMIT,
    }),
  );
  const pages = pagesQuery.data?.items ?? [];
  const selectedIds = [...selectedUrlIds];
  const toggleUrl = (siteUrlId: string) => {
    const next = new Set(selectedUrlIds);
    if (next.has(siteUrlId)) next.delete(siteUrlId);
    else next.add(siteUrlId);
    onSelectionChange?.(next);
  };

  return (
    <div className="min-h-40 p-4">
      {pagesQuery.isLoading ? (
        <div className="grid gap-2" aria-label="Loading page kind URLs">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
      ) : pagesQuery.isError ? (
        <p className="text-danger-text text-sm">Could not load URLs for this page kind.</p>
      ) : (
        <div className="grid gap-3">
          {pages.map((page) => (
            <label
              key={page.site_url_id}
              className="border-border-subtle flex items-center gap-3 border-b py-2 last:border-0"
            >
              <input
                type="checkbox"
                checked={selectedUrlIds.has(page.site_url_id)}
                onChange={() => toggleUrl(page.site_url_id)}
              />
              <span className="mono min-w-0 flex-1 truncate text-xs">{page.display_url}</span>
              <Badge variant="status" value={pageStatusBadgeValue(page.analysis_status)}>
                {statusLabel(page.analysis_status)}
              </Badge>
              <span className={cn('mono text-xs font-medium', scoreTextClass(page.overall_score))}>
                {formatScore(page.overall_score)}
              </span>
            </label>
          ))}
          {pages.length === 0 ? (
            <p className="text-secondary text-sm">No analyzed URLs in this category.</p>
          ) : null}
          <div className="flex items-center justify-between gap-3">
            <Button
              size="sm"
              onClick={() => onReanalyze?.(selectedIds)}
              disabled={selectedIds.length === 0 || reanalyzePending || !onReanalyze}
            >
              {reanalyzePending ? 'Starting…' : 'Re-analyze selected'}
            </Button>
            <CursorPager
              canPrev={pager.canPrev}
              canNext={Boolean(pagesQuery.data?.next_cursor)}
              onPrev={pager.pop}
              onNext={() => pager.push(pagesQuery.data?.next_cursor ?? null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
