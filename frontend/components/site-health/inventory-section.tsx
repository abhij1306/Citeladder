'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Card, CardContent } from '@/components/ui/card';
import { CursorPager } from '@/components/ui/cursor-pager';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Label } from '@/components/ui/typography';
import { PageKindSelect } from '@/components/site-health/page-kind-select';
import { PagesTable } from '@/components/site-health/pages-table';
import { RootErrorsBlock } from '@/components/site-health/root-errors-block';
import { siteHealthQueries, type PagesParams } from '@/lib/api/site-health';
import type { PagesPage, SiteCrawl } from '@/lib/api/types';
import { segmentedItemClasses, segmentedTrackClasses } from '@/components/ui/segmented';
import { cn } from '@/lib/utils';
import { useCursorStack } from '@/lib/site-health/use-cursor-stack';
import { PAGE_LIMIT, statusLabel, type InventoryMode } from '@/lib/site-health/status';

/**
 * Always-mounted inventory section of the canonical Site Health screen.
 *
 * ONE persistent region that renders the crawl's pages through the whole
 * lifecycle — the rows enrich in place instead of the screen swapping:
 *   - 'discovering': read-only rows streaming in as discovery finds them;
 *   - 'scored':      the tabbed (monitored / all / errors) page browser used
 *                    BOTH while analysis runs and after it finishes — statuses
 *                    move queued → running → completed and scores fill in on
 *                    the same rows (no separate "analyzing" table);
 *   - 'none':        an in-section empty state (nothing discovered yet).
 *
 * The section wrapper (and its `data-testid`) never unmounts across modes —
 * that stability is asserted by the screen regression tests.
 */
export function InventorySection({
  mode,
  crawl,
  active,
}: Readonly<{
  mode: InventoryMode;
  crawl: SiteCrawl | null;
  /** True while the crawl is non-terminal (keeps inventory/pages polling). */
  active: boolean;
}>) {
  let content: ReactNode;
  if (mode === 'none' || !crawl) {
    content = (
      <Card>
        <CardContent className="py-6 text-center">
          <p className="text-secondary text-sm">Pages appear here as discovery finds them.</p>
        </CardContent>
      </Card>
    );
  } else if (mode === 'discovering') {
    content = <DiscoveringInventory crawl={crawl} />;
  } else {
    content = <ScoredInventory crawl={crawl} active={active} />;
  }

  return (
    <div className="grid min-w-0 gap-2" data-testid="inventory-section">
      {content}
    </div>
  );
}

/**
 * Read-only admitted-URL inventory while discovery runs (bounded to this
 * crawl). The first page keeps polling so new URLs stream in; deeper pages
 * stay stable under keyset (normalized_url, id) ordering.
 */
function DiscoveringInventory({ crawl }: Readonly<{ crawl: SiteCrawl }>) {
  const pager = useCursorStack();
  // No timer here: the screen polls the crawl once and invalidates this query's
  // FIRST page when the crawl actually moved (`invalidateCrawlViews`). Deeper
  // cursor pages stay static either way, so the rows under review don't shift
  // as new URLs are discovered.
  const inventoryQuery = useQuery(
    siteHealthQueries.inventory(crawl.id, { cursor: pager.cursor, limit: PAGE_LIMIT }),
  );
  const rows = inventoryQuery.data?.items ?? [];
  const nextCursor = inventoryQuery.data?.next_cursor ?? null;

  let body: ReactNode;
  if (inventoryQuery.isError) {
    body = <Alert tone="danger">Could not load the page inventory. Please refresh.</Alert>;
  } else if (rows.length === 0) {
    body = (
      <p className="text-secondary text-sm">
        Discovering pages — sitemaps and internal links are being scanned.
      </p>
    );
  } else {
    body = (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Page URL</TableHead>
            <TableHead>Source</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.site_url_id}>
              <TableCell>
                {/* Clamped for the same reason as the scored table: a long
                    query-string URL is one unbreakable token and would size
                    the column to its full width. */}
                <span
                  className="mono text-foreground block max-w-[40rem] truncate text-xs"
                  title={row.display_url}
                >
                  {row.display_url}
                </span>
              </TableCell>
              <TableCell className="text-secondary text-xs">
                {row.source ? statusLabel(row.source) : '—'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );
  }

  return (
    <Card>
      <CardContent className="grid gap-2">
        <Label>Pages discovered so far</Label>
        {body}
        <div className="flex flex-wrap items-center justify-between gap-3">
          {crawl.status === 'running' || crawl.status === 'queued' ? (
            <p className="text-muted text-xs">More URLs appear as discovery continues.</p>
          ) : (
            <span />
          )}
          {pager.canPrev || nextCursor ? (
            <div className="flex items-center gap-2">
              <CursorPager
                canPrev={pager.canPrev}
                canNext={Boolean(nextCursor)}
                onPrev={pager.pop}
                onNext={() => pager.push(nextCursor)}
              />
            </div>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

/** The three server-backed page tabs (design mockup 713). */
type TabKey = 'monitored' | 'all' | 'errors';

const TABS: ReadonlyArray<{ key: TabKey; label: string; params: PagesParams }> = [
  { key: 'monitored', label: 'Monitored', params: { monitored: true } },
  { key: 'all', label: 'All Discovered', params: {} },
  { key: 'errors', label: 'Errors & Blocked', params: { status: 'error_or_blocked' } },
];

/**
 * The page browser (design mockup 713): three server-backed tabs, each its
 * OWN query with its own cursor stack — filtering is server-side, never a
 * filter over the current client page.
 *
 * Used for the WHOLE audit lifecycle: while analysis runs the first page of
 * the active tab polls, so each row's status badge advances queued → running
 * → completed and its scores fill in — the SAME rows, in place, until the run
 * settles. Finishing changes nothing structurally.
 */
function ScoredInventoryBody({
  query,
  rows,
  rootErrors,
  active,
  crawlId,
}: Readonly<{
  query: { isError: boolean; isLoading: boolean };
  rows: PagesPage['items'];
  rootErrors: NonNullable<PagesPage['root_errors']>;
  active: boolean;
  crawlId: string;
}>) {
  if (query.isError)
    return (
      <div className="p-[var(--card-padding)]">
        <Alert tone="danger">Could not load pages for this view. Try again.</Alert>
      </div>
    );
  if (query.isLoading)
    return (
      <div className="grid min-h-40 gap-2 p-[var(--card-padding)]">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  if (rows.length === 0 && rootErrors.length === 0)
    return (
      <p className="text-secondary p-[var(--card-padding)] text-sm">
        {active ? 'Pages appear here as the audit reaches them.' : 'No pages in this view.'}
      </p>
    );
  return (
    <div className="grid gap-3 p-[var(--card-padding)]">
      <RootErrorsBlock errors={rootErrors} />
      {rows.length > 0 ? <PagesTable pages={rows} crawlId={crawlId} /> : null}
    </div>
  );
}

function ScoredInventory({
  crawl,
  active,
}: Readonly<{
  crawl: SiteCrawl;
  active: boolean;
}>) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<TabKey>('monitored');
  // Shared page-kind filter (v2 P1): one server-backed value that composes
  // with whichever tab is active — never a client filter over the page window.
  const [pageKind, setPageKind] = useState('');
  // Per-tab cursor stack so Prev/Next walk keyset pages without offsets.
  const monitoredPager = useCursorStack();
  const allPager = useCursorStack();
  const errorsPager = useCursorStack();
  const pager = tab === 'monitored' ? monitoredPager : tab === 'all' ? allPager : errorsPager;
  const resetMonitoredPager = monitoredPager.reset;

  // The monitored query changes from `status=completed` to the full projection
  // when a crawl becomes terminal. Its cursor is filter-bound, so never carry a
  // deeper active-view cursor across that boundary.
  useEffect(() => {
    resetMonitoredPager();
  }, [active, resetMonitoredPager]);

  const activeTab = TABS.find((t) => t.key === tab)!;
  // A recrawl pre-seeds every monitored URL as pending. Showing that full
  // pending window immediately makes the table appear frozen and then burst
  // all at once. The first active view instead asks the persisted projection
  // for completed rows, so audited pages arrive progressively. The other tabs
  // remain available, and the terminal Monitored view returns to the complete
  // monitored set.
  const activeTabParams: PagesParams =
    active && tab === 'monitored' ? { ...activeTab.params, status: 'completed' } : activeTab.params;

  // A filter edit restarts EVERY tab from its first page — cursors are
  // filter-bound server-side, so a stale cursor under a new page type 400s.
  const selectPageKind = (next: string) => {
    setPageKind(next);
    monitoredPager.reset();
    allPager.reset();
    errorsPager.reset();
  };

  // No timer here either: the screen's single crawl subscription invalidates
  // the FIRST page of every tab when the crawl moved, so rows advance
  // queued → running → completed in place. Deeper cursor pages stay static so
  // rows under review don't shift as more pages finish scoring.
  const pagesQuery = useQuery(
    siteHealthQueries.pages(crawl.id, {
      ...activeTabParams,
      page_kind: pageKind || undefined,
      cursor: pager.cursor,
      limit: PAGE_LIMIT,
    }),
  );
  const prefetchTab = (nextTab: (typeof TABS)[number]) => {
    void queryClient.prefetchQuery(
      siteHealthQueries.pages(crawl.id, {
        ...nextTab.params,
        page_kind: pageKind || undefined,
        limit: PAGE_LIMIT,
      }),
    );
  };

  const rows = pagesQuery.data?.items ?? [];
  const nextCursor = pagesQuery.data?.next_cursor ?? null;
  // B3 (SH-4): the root fetch's failed calls ride the pages response. They
  // render ONLY on the Errors & Blocked tab, above the table, as a distinct
  // non-clickable block — the `error_or_blocked` filter keeps its real-page
  // semantics (a root failure never created a page row).
  const rootErrors = tab === 'errors' ? (pagesQuery.data?.root_errors ?? []) : [];

  const body = (
    <ScoredInventoryBody
      query={pagesQuery}
      rows={rows}
      rootErrors={rootErrors}
      active={active}
      crawlId={crawl.id}
    />
  );

  return (
    <Card>
      <CardContent className="grid gap-4 p-0">
        <div className="border-border-subtle flex flex-wrap items-center gap-2 border-b px-[var(--card-padding)] pt-[var(--card-padding)]">
          <div className={cn(segmentedTrackClasses, 'flex flex-wrap')}>
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                onMouseEnter={() => prefetchTab(t)}
                onFocus={() => prefetchTab(t)}
                aria-current={t.key === tab ? 'true' : undefined}
                className={segmentedItemClasses(t.key === tab)}
              >
                {active && tab === 'monitored' && t.key === 'monitored'
                  ? 'Audited so far'
                  : t.label}
              </button>
            ))}
          </div>
          <div className="mb-1 ml-auto flex items-center gap-2">
            <PageKindSelect value={pageKind} onChange={selectPageKind} />
          </div>
        </div>

        {body}

        {pager.canPrev || nextCursor ? (
          <div className="border-border-subtle flex items-center justify-end gap-2 border-t px-[var(--card-padding)] py-3">
            <CursorPager
              canPrev={pager.canPrev}
              canNext={Boolean(nextCursor)}
              onPrev={pager.pop}
              onNext={() => pager.push(nextCursor)}
            />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
