'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { CursorPager } from '@/components/ui/cursor-pager';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Label } from '@/components/ui/typography';
import { InventoryTable } from '@/components/site-health/inventory-table';
import { PageKindSelect } from '@/components/site-health/page-kind-select';
import { QuickSelectBar } from '@/components/site-health/quick-select-bar';
import { SelectionNotices } from '@/components/site-health/selection-notices';
import { mutationNoticeForError } from '@/lib/api/mutation-notice';
import { siteHealthQueries } from '@/lib/api/site-health';
import type { SiteCrawl, SiteHealthEntitlement } from '@/lib/api/types';
import { cn } from '@/lib/utils';
import {
  changeInventoryFilters,
  emptyInventoryFilters,
  toInventoryParams,
  type InventoryFilters,
} from '@/lib/site-health/filters';
import {
  allStaged,
  commitCtaLabel,
  setManyStaged,
  toggleStaged,
} from '@/lib/site-health/selection';
import { useMonitoredSelection } from '@/lib/site-health/use-monitored-selection';
import { useCursorStack } from '@/lib/site-health/use-cursor-stack';
import { PAGE_LIMIT } from '@/lib/site-health/status';

/**
 * Starter monitored-selection (Slice 7, mockup 709).
 *
 * A cursor-paginated inventory with search/status filters where the user stages
 * the persistent monitored set. Staging/commit/bulk semantics (including stale
 * `selection_version` recovery) live in `useMonitoredSelection`; this component
 * owns only the inventory pagination/filters and layout.
 *
 * Also serves a CANCELLED crawl (`crawlInactive`): the discovered inventory
 * survives a cancel, so the user can still browse it and stage/commit a
 * monitored set. Running that set is not this panel's job — analysis tasks
 * only enqueue into an active crawl, and starting one is "Re-crawl site" in
 * the phase controls.
 */
export function InventorySelection({
  crawl,
  entitlement,
  projectId,
  crawlInactive = false,
  onCancel,
  cancelPending = false,
}: Readonly<{
  crawl: SiteCrawl;
  entitlement: SiteHealthEntitlement;
  projectId: string;
  /** True when the crawl is terminal (cancelled) — analysis needs a new crawl. */
  crawlInactive?: boolean;
  onCancel?: () => void;
  cancelPending?: boolean;
}>) {
  const [filters, setFilters] = useState<InventoryFilters>(emptyInventoryFilters);
  const pager = useCursorStack();
  const [searchInput, setSearchInput] = useState('');

  const inventoryQuery = useQuery(
    siteHealthQueries.inventory(crawl.id, {
      ...toInventoryParams(filters, pager.cursor, PAGE_LIMIT),
    }),
  );

  const rows = inventoryQuery.data?.items ?? [];
  const nextCursor = inventoryQuery.data?.next_cursor ?? null;

  const homepageId = inventoryQuery.data?.items.find(
    (row) => row.normalized_url === crawl.root_url,
  )?.site_url_id;

  const {
    monitoredQuery,
    effectiveSelection,
    setSelection,
    delta,
    quota,
    staleNotice,
    replaceMutation,
    bulkSelectMutation,
    bulkSelect,
    bulkSelectError,
    commit,
  } = useMonitoredSelection({
    crawl,
    entitlement,
    projectId,
    homepageId,
    // Don't initialize the staging session until the inventory has settled —
    // the homepage lookup above is only meaningful once rows are loaded.
    inventoryReady: inventoryQuery.isSuccess,
    searchQuery: filters.query,
  });

  const visibleIds = rows.map((row) => row.site_url_id);
  const allVisibleStaged = effectiveSelection ? allStaged(effectiveSelection, visibleIds) : false;

  const applyFilters = (next: Partial<InventoryFilters>) => {
    const changed = changeInventoryFilters(filters, next);
    setFilters(changed.filters);
    pager.reset();
  };

  if (monitoredQuery.isLoading || inventoryQuery.isLoading) {
    return (
      <Card>
        <CardContent className="grid gap-3">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-40 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (monitoredQuery.isError || inventoryQuery.isError) {
    return <Alert tone="danger">Could not load the page inventory. Please refresh.</Alert>;
  }

  return (
    <Card>
      <CardContent className="grid gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="grid gap-0.5">
            <Label>Page Inventory</Label>
            <span className="text-secondary text-sm">
              Select pages to include in your health analysis — selections persist across re-crawls.
            </span>
          </div>
          {quota ? (
            <div className="flex items-center gap-3">
              <span
                className={cn(
                  'mono text-sm font-medium',
                  quota.overLimit ? 'text-danger-text' : 'text-secondary',
                )}
              >
                {quota.staged} of {quota.limit} selected
              </span>
              {!crawlInactive && onCancel ? (
                <Button variant="destructive" size="sm" onClick={onCancel} disabled={cancelPending}>
                  {cancelPending ? 'Cancelling…' : 'Cancel'}
                </Button>
              ) : null}
            </div>
          ) : !crawlInactive && onCancel ? (
            <Button variant="destructive" size="sm" onClick={onCancel} disabled={cancelPending}>
              {cancelPending ? 'Cancelling…' : 'Cancel'}
            </Button>
          ) : null}
        </div>

        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            applyFilters({ query: searchInput });
          }}
        >
          <Input
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search pages…"
            className="max-w-xs"
            aria-label="Search pages"
          />
          <Button type="submit" variant="secondary" size="sm">
            Search
          </Button>
          {/* Page-type filter (v2 P1): same server-backed wiring + cursor
              reset as the search filter via `applyFilters`. */}
          <PageKindSelect
            value={filters.page_kind}
            onChange={(value) => applyFilters({ page_kind: value })}
          />
          {effectiveSelection ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() =>
                setSelection(setManyStaged(effectiveSelection, visibleIds, !allVisibleStaged))
              }
            >
              {allVisibleStaged ? 'Clear visible' : 'Select visible'}
            </Button>
          ) : null}
        </form>

        {effectiveSelection && entitlement.access_mode === 'full' ? (
          <QuickSelectBar
            maxCount={entitlement.monitored_url_limit}
            pending={bulkSelectMutation.isPending}
            onBulkSelect={bulkSelect}
          />
        ) : null}

        <SelectionNotices
          bulkNotice={
            bulkSelectMutation.isError
              ? (() => {
                  const notice = mutationNoticeForError(bulkSelectMutation.error, {
                    action: 'apply the bulk selection',
                  });
                  // The quota-specific guidance (from the 403 detail) wins over
                  // the generic verbatim message when it applies.
                  return bulkSelectError ? { ...notice, message: bulkSelectError } : notice;
                })()
              : null
          }
          onBulkRetry={() => {
            if (bulkSelectMutation.variables) {
              bulkSelectMutation.mutate(bulkSelectMutation.variables);
            }
          }}
          quota={quota}
          staleNotice={staleNotice}
          replaceNotice={
            replaceMutation.isError
              ? mutationNoticeForError(replaceMutation.error, { action: 'save your selection' })
              : null
          }
          onReplaceRetry={commit}
        />

        <InventoryTable
          rows={rows}
          isStaged={(id) => effectiveSelection?.staged.has(id) ?? false}
          disabled={!effectiveSelection}
          onToggle={(id) =>
            effectiveSelection && setSelection(toggleStaged(effectiveSelection, id))
          }
        />

        <div className="border-border-subtle flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <div className="flex items-center gap-2">
            <CursorPager
              canPrev={pager.canPrev}
              canNext={Boolean(nextCursor)}
              onPrev={pager.pop}
              onNext={() => pager.push(nextCursor)}
            />
          </div>
          <div className="flex items-center gap-3">
            <span className="text-muted text-xs">
              Selections are saved and persist across re-crawls.
            </span>
            <Button
              size="sm"
              variant={crawlInactive && !delta?.dirty ? 'secondary' : 'primary'}
              onClick={commit}
              disabled={
                !effectiveSelection ||
                !delta?.dirty ||
                quota?.overLimit ||
                replaceMutation.isPending
              }
            >
              {replaceMutation.isPending
                ? 'Saving…'
                : effectiveSelection
                  ? crawlInactive
                    ? `Save selection (${effectiveSelection.staged.size} of ${entitlement.monitored_url_limit})`
                    : commitCtaLabel(effectiveSelection, entitlement.monitored_url_limit)
                  : 'Analyze pages'}
            </Button>
            {/* No second "Start analysis" here. A cancelled crawl cannot
                enqueue analyze tasks, so analysis means a fresh crawl seeded
                with the committed set — which is exactly what "Re-crawl site"
                in the phase controls does. Two identically-labelled buttons
                that both created a crawl was the ambiguity; this panel's job
                ends at saving the selection. */}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
