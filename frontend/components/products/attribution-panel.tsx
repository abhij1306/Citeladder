'use client';

import { useState } from 'react';
import { ChevronDown, Inbox, RefreshCw } from 'lucide-react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardEyebrow,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Dropdown,
  DropdownContent,
  DropdownLabel,
  DropdownRadioGroup,
  DropdownRadioItem,
  DropdownTrigger,
} from '@/components/ui/dropdown';
import { SegmentedControl } from '@/components/ui/segmented-control';
import { Skeleton } from '@/components/ui/skeleton';
import { MutationNotice } from '@/components/ui/mutation-notice';
import { IconChip } from '@/components/ui/icon-chip';
import { displayHeadingLgClasses } from '@/components/ui/typography';
import { mutationNoticeForError } from '@/lib/api/mutation-notice';
import { formatCount, formatUtcTimestamp } from '@/lib/format';
import { formatPercent } from '@/lib/products/catalog';
import {
  ATTRIBUTION_SUB_TABS,
  GRANULARITY_OPTIONS,
  RANGE_OPTIONS,
  buildAttributionBlocks,
  isActiveAttributionTask,
  rangeLabel,
  type AttributionSubTab,
} from '@/lib/products/attribution';
import type { useAttributionQueries } from '@/lib/products/use-products-screen';
import { syncRunStatusLabel } from '@/lib/integrations/sync-runs';

import { AttributionMethodComparison } from './attribution-method-comparison';
import { AttributionProductTable } from './attribution-product-table';
import { AttributionSourceTable } from './attribution-source-table';
import { NestedTabs } from './nested-tabs';
import { StatisticalAllocationCard } from './statistical-allocation-card';

type AttributionQueries = ReturnType<typeof useAttributionQueries>;

/**
 * Attribution tab (agentic commerce): the persisted A1 (GA4
 * platform-attributed) vs A2 (Shopify order referrer) snapshot. A local
 * toolbar (Range preset, Day/Week/Month granularity, Recompute) sits ABOVE
 * the nested sub-tablist and slices every sub-panel: `overview` (per-currency
 * A1/A2 method cards, the backend delta, the unattributed remainder, and the
 * statistical estimate when offered), `by-source` (the deterministic
 * per-source table), and `by-product` (the per-SKU table). Methods are never
 * summed, currencies never converted, and a missing snapshot renders the
 * empty contract honestly (the endpoint returns one, never a 404).
 */
export function AttributionPanel({
  queries,
}: Readonly<{
  // Part of the panel's public API (the screen passes it); every query lives
  // on `queries`, so the component body never reads the id itself.
  projectId: string;
  queries: AttributionQueries;
}>) {
  const {
    range,
    setRange,
    granularity,
    setGranularity,
    snapshotQuery,
    recomputeMutation,
    recomputeTaskQuery,
  } = queries;
  const [subTab, setSubTab] = useState<AttributionSubTab>('overview');

  const recomputeTask = recomputeTaskQuery.data;
  const recomputeActive =
    recomputeMutation.isPending ||
    (recomputeTask !== undefined && isActiveAttributionTask(recomputeTask.status));
  const recomputeFailed =
    recomputeTask !== undefined &&
    (recomputeTask.status === 'failed' || recomputeTask.status === 'cancelled');

  if (snapshotQuery.isLoading) {
    return <AttributionSkeleton />;
  }

  if (snapshotQuery.isError) {
    return (
      <Card>
        <CardContent>
          <div className="grid justify-items-center gap-3 py-10 text-center">
            <CardEyebrow>Attribution</CardEyebrow>
            <h3 className={displayHeadingLgClasses}>Couldn&apos;t load attribution</h3>
            <p className="text-secondary max-w-xs text-sm">
              The request failed or timed out. Your filters are unchanged.
            </p>
            <Button variant="primary" size="sm" onClick={() => snapshotQuery.refetch()}>
              <RefreshCw className="size-4" aria-hidden />
              Retry
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  const snapshot = snapshotQuery.data;
  if (!snapshot) return <AttributionSkeleton />;

  const blocks = buildAttributionBlocks(snapshot);
  const multiCurrency = blocks.length > 1;
  const singleCurrency = blocks.length === 1 ? blocks[0].currency : null;

  const toolbar = (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2" data-testid="attribution-toolbar">
        <Dropdown>
          <DropdownTrigger asChild>
            <Button variant="secondary" size="sm" aria-label="Select date range">
              <span className="text-muted">Range:</span>
              <span className="font-medium">{rangeLabel(range)}</span>
              <ChevronDown className="text-muted size-3" aria-hidden />
            </Button>
          </DropdownTrigger>
          <DropdownContent>
            <DropdownLabel>Date range</DropdownLabel>
            <DropdownRadioGroup value={range}>
              {RANGE_OPTIONS.map((option) => (
                <DropdownRadioItem
                  key={option.value}
                  value={option.value}
                  onSelect={() => setRange(option.value)}
                >
                  {option.label}
                </DropdownRadioItem>
              ))}
            </DropdownRadioGroup>
          </DropdownContent>
        </Dropdown>

        <SegmentedControl
          value={granularity}
          onChange={setGranularity}
          options={GRANULARITY_OPTIONS}
          ariaLabel="Granularity"
        />

        <div className="ml-auto flex items-center gap-2">
          {recomputeActive && recomputeTask ? (
            <Badge variant="status" value="info">
              {syncRunStatusLabel(recomputeTask.status)}
            </Badge>
          ) : null}
          <Button
            variant="primary"
            size="sm"
            disabled={recomputeActive}
            onClick={() => recomputeMutation.mutate()}
          >
            <RefreshCw className={recomputeActive ? 'size-4 animate-spin' : 'size-4'} aria-hidden />
            {recomputeActive ? 'Recomputing…' : 'Recompute'}
          </Button>
        </div>
      </div>

      <div className="text-muted flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <span>
          {singleCurrency
            ? `Reported in ${singleCurrency} · native currency, no conversion applied`
            : 'Reported in native currencies · no conversion applied'}
        </span>
        {snapshot.created_at ? (
          <Badge variant="neutral">Snapshot {formatUtcTimestamp(snapshot.created_at)}</Badge>
        ) : null}
      </div>
    </div>
  );

  const recomputeNotices = (
    <>
      {recomputeMutation.isError ? (
        // A4/COM-6: a 4xx precondition (e.g. "no completed sync window is
        // available") renders the backend message verbatim — no futile
        // "try again"; only transient failures offer the retry affordance.
        <MutationNotice
          notice={mutationNoticeForError(recomputeMutation.error, {
            action: 'start the attribution recompute',
          })}
          onRetry={() => recomputeMutation.mutate()}
        />
      ) : null}
      {recomputeFailed ? (
        <Alert tone="warning">
          The attribution recompute {recomputeTask.status === 'failed' ? 'failed' : 'was cancelled'}
          {recomputeTask.error_code ? ` (${recomputeTask.error_code})` : ''}. The current snapshot
          stays on screen.
        </Alert>
      ) : null}
    </>
  );

  if (blocks.length === 0) {
    return (
      <div className="grid gap-4">
        {toolbar}
        {recomputeNotices}
        <Card>
          <CardContent className="grid justify-items-center gap-4 py-12 text-center">
            <CardEyebrow>Attribution</CardEyebrow>
            <IconChip className="bg-neutral-bg text-muted">
              <Inbox className="size-5" aria-hidden />
            </IconChip>
            <div className="grid gap-1">
              <h2 className={displayHeadingLgClasses}>No attribution snapshot yet</h2>
              <p className="text-secondary max-w-md text-sm">
                Attribution compares GA4 platform-attributed revenue (A1) with Shopify
                order-referrer revenue (A2) — side by side, never summed. Connect a revenue source
                in Settings › Integrations, then Recompute to persist a snapshot for this window.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  const panel =
    subTab === 'by-source' ? (
      <div className="grid gap-4">
        {blocks.map((block) => (
          <CurrencyBlockSection
            key={block.currency ?? 'unavailable'}
            currency={block.currency}
            showHeading={multiCurrency}
          >
            <AttributionSourceTable block={block} />
          </CurrencyBlockSection>
        ))}
      </div>
    ) : subTab === 'by-product' ? (
      <div className="grid gap-4">
        {blocks.map((block) => (
          <CurrencyBlockSection
            key={block.currency ?? 'unavailable'}
            currency={block.currency}
            showHeading={multiCurrency}
          >
            <AttributionProductTable block={block} />
          </CurrencyBlockSection>
        ))}
      </div>
    ) : (
      <div className="grid gap-4">
        <AttributionCoverageCard coverage={snapshot.metrics.deterministic.coverage} />
        {blocks.map((block) => (
          <CurrencyBlockSection
            key={block.currency ?? 'unavailable'}
            currency={block.currency}
            showHeading={multiCurrency}
          >
            <div className="grid gap-4">
              <AttributionMethodComparison block={block} />
              <StatisticalAllocationCard
                statistical={snapshot.metrics.statistical}
                currency={block.currency}
              />
            </div>
          </CurrencyBlockSection>
        ))}
      </div>
    );

  return (
    <div className="grid gap-4">
      {toolbar}
      {recomputeNotices}
      <NestedTabs
        tabs={ATTRIBUTION_SUB_TABS}
        activeTab={subTab}
        onSelectTab={setSubTab}
        ariaLabel="Attribution views"
        idPrefix="attribution"
        panel={panel}
      />
    </div>
  );
}

function AttributionCoverageCard({
  coverage,
}: Readonly<{
  coverage: NonNullable<
    AttributionQueries['snapshotQuery']['data']
  >['metrics']['deterministic']['coverage'];
}>) {
  const metrics = [
    ['Latest orders', formatCount(coverage.total_latest_orders)],
    ['Orders with evidence', formatCount(coverage.orders_with_evidence)],
    ['Linked AI orders', formatCount(coverage.linked_ai_orders)],
    ['Unattributed orders', formatCount(coverage.unattributed_orders)],
    ['Evidence coverage', formatPercent(coverage.evidence_coverage_rate)],
    ['Attributed share', formatPercent(coverage.attributed_share)],
  ] as const;
  return (
    <Card aria-label="Attribution coverage">
      <CardHeader>
        <CardEyebrow>A2 evidence horizon</CardEyebrow>
        <CardTitle>Attribution coverage</CardTitle>
        <CardDescription>
          Latest Shopify order revisions from {coverage.window_start || '—'} through{' '}
          {coverage.window_end || '—'}.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {metrics.map(([label, value]) => (
          <div key={label} className="grid gap-1">
            <span className="text-muted text-xs">{label}</span>
            <span className="text-foreground mono text-sm font-medium tabular-nums">{value}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

/**
 * One ISO currency partition. A heading appears only when the snapshot holds
 * more than one currency — the partitions stay visually separate so no one
 * reads them as a combinable total.
 */
function CurrencyBlockSection({
  currency,
  showHeading,
  children,
}: Readonly<{
  currency: string | null;
  showHeading: boolean;
  children: React.ReactNode;
}>) {
  if (!showHeading) return <>{children}</>;
  return (
    <section className="grid gap-3" aria-label={currency ?? 'Unavailable methods'}>
      <h3 className="text-muted text-xs font-medium">{currency ?? 'Unavailable methods'}</h3>
      {children}
    </section>
  );
}

function AttributionSkeleton() {
  return (
    <div className="grid gap-4" aria-hidden>
      <Skeleton className="h-8 w-112 max-w-full" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Skeleton className="h-56 w-full" />
        <Skeleton className="h-56 w-full" />
      </div>
      <Skeleton className="h-40 w-full" />
    </div>
  );
}
