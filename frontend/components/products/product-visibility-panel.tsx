'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ChevronDown, Download, Inbox, Package, RefreshCw } from 'lucide-react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardEyebrow, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dropdown,
  DropdownContent,
  DropdownLabel,
  DropdownRadioGroup,
  DropdownRadioItem,
  DropdownTrigger,
} from '@/components/ui/dropdown';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { displayHeadingLgClasses } from '@/components/ui/typography';
import { ApiError } from '@/lib/api/errors';
import { productsApi } from '@/lib/api/products';
import type { CompetitorProductVisibilityEntry, ProductVisibilityEntry } from '@/lib/api/types';
import { engineLabel } from '@/lib/providers/catalog';
import {
  RANK_BUCKET_LABELS,
  RANK_BUCKET_ORDER,
  VISIBILITY_SUB_TABS,
  aggregateAttributeFrequency,
  aggregateBuyerDestinationMix,
  buildCoPlacementMatrix,
  formatAvgRank,
  formatPercent,
  hasDirectionUnavailableRows,
  priceRelationDisplay,
  summarizeProductVisibility,
  type VisibilitySubTab,
} from '@/lib/products/catalog';
import type { useProductVisibilityQueries } from '@/lib/products/use-products-screen';
import { cn } from '@/lib/utils';

import { AttributeFrequencyPanel } from './attribute-frequency-panel';
import { BuyerDestinationBreakdown } from './buyer-destination-breakdown';
import { CompetitorCoPlacementMatrix } from './competitor-co-placement-matrix';
import { EngineFilterDropdown } from './engine-filter-dropdown';
import { NestedTabs } from '@/components/ui/nested-tabs';
import { SurfaceFilterDropdown } from './surface-filter-dropdown';

type VisibilityQueries = ReturnType<typeof useProductVisibilityQueries>;

const RANK_SEGMENT_CLASS: Record<(typeof RANK_BUCKET_ORDER)[number], string> = {
  top_1: 'bg-success',
  top_2_3: 'bg-info',
  top_4_5: 'bg-warning',
  rank_6_plus: 'bg-danger',
  unranked: 'bg-border-bold',
};

/** Exact v1 mixed-version alert copy (analyzer v1 recorded no direction). */
const V1_DIRECTION_ALERT =
  'Analyzed by product analyzer v1 — price direction was not recorded for these mentions.';

/**
 * Visibility tab (agentic commerce): the selected run's product-vs-competitor
 * projection. The Run/Engine/Surface/Export toolbar sits ABOVE the nested
 * sub-tablist and slices all four sub-panels: `overview` (summary strip +
 * own/competitor rankings with win rate and price relation), `attributes`
 * (dimension frequency), `destinations` (buyer-destination mix), and
 * `co-placement` (the competitor matrix). All values are persisted backend
 * aggregates; states mirror the visibility evidence-states gallery
 * (skeleton / retryable error / no-audit empty / no-catalog CTA).
 */
export function ProductVisibilityPanel({
  projectId,
  queries,
  onGoToCatalog,
}: Readonly<{
  projectId: string;
  queries: VisibilityQueries;
  onGoToCatalog: () => void;
}>) {
  const {
    runOptions,
    activeRunId,
    selectRun,
    engine,
    setEngine,
    engineParam,
    surface,
    setSurface,
    visibilityQuery,
  } = queries;
  const [subTab, setSubTab] = useState<VisibilitySubTab>('overview');

  if (visibilityQuery.isLoading) {
    return <VisibilitySkeleton />;
  }

  if (visibilityQuery.isError) {
    const error = visibilityQuery.error;
    // 404 = no completed run with product metrics yet (no-audit) OR the run
    // predates / lacks a catalog (no-catalog CTA).
    if (error instanceof ApiError && error.status === 404) {
      // When the 404 is for a run the user explicitly picked (e.g. a
      // brand-only audit), keep the run selector on screen — otherwise the
      // selection sticks (it lives in screen-level state) and the only way
      // back to "Latest" is a full page reload.
      if (activeRunId) {
        return (
          <div className="grid gap-4">
            <div
              className="flex flex-wrap items-center gap-2"
              data-testid="product-visibility-toolbar"
            >
              <RunSelectorDropdown
                runOptions={runOptions}
                activeRunId={activeRunId}
                selectRun={selectRun}
              />
            </div>
            <NoAuditEmpty onGoToCatalog={onGoToCatalog} selectedRun />
          </div>
        );
      }
      return <NoAuditEmpty onGoToCatalog={onGoToCatalog} />;
    }
    return (
      <Card>
        <CardContent>
          <div className="grid justify-items-center gap-3 py-10 text-center">
            <CardEyebrow>Product visibility</CardEyebrow>
            <h3 className={displayHeadingLgClasses}>Couldn&apos;t load product visibility</h3>
            <p className="text-secondary max-w-xs text-sm">
              The request failed or timed out. Your filters are unchanged.
            </p>
            <Button variant="primary" size="sm" onClick={() => visibilityQuery.refetch()}>
              <RefreshCw className="size-4" aria-hidden />
              Retry
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  const visibility = visibilityQuery.data;
  if (!visibility) return <VisibilitySkeleton />;

  // D2 state (b): the selected run COMPLETED but recorded zero product
  // mentions in this slice — explain why and what to do, never the wall of
  // zeros (COM-1/COM-2). The toolbar stays so the run/engine/surface slice
  // can be changed in place.
  if (visibility.total_mentions === 0) {
    return (
      <div className="grid gap-4">
        <VisibilityToolbar
          projectId={projectId}
          runOptions={runOptions}
          activeRunId={activeRunId}
          selectRun={selectRun}
          engine={engine}
          setEngine={setEngine}
          engineParam={engineParam}
          surfaces={visibility.available_surfaces}
          surface={surface}
          setSurface={setSurface}
        />
        <NoMentionsEmpty
          engineParam={engineParam}
          surface={surface}
          onGoToCatalog={onGoToCatalog}
        />
      </div>
    );
  }

  const summary = summarizeProductVisibility(visibility);
  const showV1Alert = hasDirectionUnavailableRows([
    ...visibility.products,
    ...visibility.competitor_products,
  ]);

  const panel =
    subTab === 'attributes' ? (
      <AttributeFrequencyPanel groups={aggregateAttributeFrequency(visibility.products)} />
    ) : subTab === 'destinations' ? (
      <BuyerDestinationBreakdown mix={aggregateBuyerDestinationMix(visibility.products)} />
    ) : subTab === 'co-placement' ? (
      <CompetitorCoPlacementMatrix matrix={buildCoPlacementMatrix(visibility.products)} />
    ) : (
      <div className="grid gap-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard
            label="Product SOV"
            value={formatPercent(summary.sov)}
            caption="Your share of all product mentions in this run"
          />
          <SummaryCard
            label="Product mentions"
            value={String(summary.ownMentions)}
            caption={`of ${summary.totalMentions} product mentions`}
          />
          <SummaryCard
            label="Avg rank in product lists"
            value={formatAvgRank(summary.avgRank)}
            caption="Average position when your products are listed"
          />
          <SummaryCard
            label="Price-mention accuracy"
            value={formatPercent(summary.priceAccuracy)}
            caption="Extracted prices matching the catalog"
          />
        </div>

        <RankingsCard
          title="Product rankings"
          description="Your products — mentions, win rate, rank distribution, and price relation for the selected run."
          rows={visibility.products}
          kind="own"
        />
        <RankingsCard
          title="Competitor products"
          description="Competitor products measured in the same run."
          rows={visibility.competitor_products}
          kind="competitor"
        />
      </div>
    );

  return (
    <div className="grid gap-4">
      <VisibilityToolbar
        projectId={projectId}
        runOptions={runOptions}
        activeRunId={activeRunId}
        selectRun={selectRun}
        engine={engine}
        setEngine={setEngine}
        engineParam={engineParam}
        surfaces={visibility.available_surfaces}
        surface={surface}
        setSurface={setSurface}
      />

      {showV1Alert ? <Alert tone="info">{V1_DIRECTION_ALERT}</Alert> : null}

      <NestedTabs
        tabs={VISIBILITY_SUB_TABS}
        activeTab={subTab}
        onSelectTab={setSubTab}
        ariaLabel="Visibility views"
        idPrefix="product-visibility"
        panel={panel}
      />
    </div>
  );
}

/** The Run/Engine/Surface/Export toolbar — shared by the data view and the
 * zero-mentions empty state so the slice stays editable in place (D2). */
function VisibilityToolbar({
  projectId,
  runOptions,
  activeRunId,
  selectRun,
  engine,
  setEngine,
  engineParam,
  surfaces,
  surface,
  setSurface,
}: Readonly<{
  projectId: string;
  runOptions: VisibilityQueries['runOptions'];
  activeRunId: string | null;
  selectRun: (id: string | null) => void;
  engine: VisibilityQueries['engine'];
  setEngine: VisibilityQueries['setEngine'];
  engineParam: string | undefined;
  surfaces: string[];
  surface: string;
  setSurface: (surface: string) => void;
}>) {
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="product-visibility-toolbar">
      <RunSelectorDropdown
        runOptions={runOptions}
        activeRunId={activeRunId}
        selectRun={selectRun}
      />

      <EngineFilterDropdown engine={engine} onChange={setEngine} />

      <SurfaceFilterDropdown surfaces={surfaces} surface={surface} onChange={setSurface} />

      <div className="ml-auto">
        <Button asChild variant="ghost" size="sm">
          <a
            href={productsApi.exportCsvUrl(projectId, {
              audit_id: activeRunId ?? undefined,
              engine: engineParam,
              surface,
            })}
            download
          >
            <Download className="size-4" aria-hidden />
            Export CSV
          </a>
        </Button>
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  caption,
}: Readonly<{ label: string; value: string; caption: string }>) {
  return (
    <Card>
      <CardContent className="grid gap-1">
        <CardEyebrow>{label}</CardEyebrow>
        <p className="font-mono text-xl tabular-nums">{value}</p>
        <p className="text-muted text-xs">{caption}</p>
      </CardContent>
    </Card>
  );
}

type RankingRow =
  | { kind: 'own'; entry: ProductVisibilityEntry }
  | { kind: 'competitor'; entry: CompetitorProductVisibilityEntry };

function RankingsCard({
  title,
  description,
  rows,
  kind,
}: Readonly<{
  title: string;
  description: string;
  rows: ProductVisibilityEntry[] | CompetitorProductVisibilityEntry[];
  kind: 'own' | 'competitor';
}>) {
  const normalized: RankingRow[] = rows.map((entry) => ({ kind, entry }) as RankingRow);
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div className="grid gap-1">
          <CardTitle>{title}</CardTitle>
          <p className="text-secondary text-sm">{description}</p>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {normalized.length === 0 ? (
          <p className="text-secondary p-[var(--card-padding)] text-sm">
            Nothing measured here in the selected run.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">#</TableHead>
                <TableHead>Product</TableHead>
                <TableHead>Mentions</TableHead>
                <TableHead>SOV</TableHead>
                <TableHead>Win rate</TableHead>
                <TableHead className="min-w-35">Rank distribution</TableHead>
                <TableHead>Avg rank</TableHead>
                <TableHead className="min-w-50">Price relation</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {normalized.map((row, index) => (
                <RankingTableRow key={rowKey(row)} row={row} position={index + 1} />
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function rowKey(row: RankingRow): string {
  if (row.kind === 'own') {
    return row.entry.product_id ?? `own:${row.entry.sku}:${row.entry.name}`;
  }
  return (
    row.entry.competitor_product_id ?? `competitor:${row.entry.competitor_name}:${row.entry.name}`
  );
}

function RankingTableRow({ row, position }: Readonly<{ row: RankingRow; position: number }>) {
  const { entry } = row;
  const subtitle = row.kind === 'own' ? row.entry.sku : row.entry.competitor_name;
  return (
    <TableRow>
      <TableCell numeric className="text-muted">
        {position}
      </TableCell>
      <TableCell className="max-w-70 min-w-45">
        <div className="grid gap-0.5">
          <span className="flex items-center gap-2">
            {row.kind === 'own' && row.entry.product_id ? (
              <Link
                href={`/products/${row.entry.product_id}`}
                className="text-foreground hover:text-accent-text truncate font-medium transition-colors"
              >
                {entry.name}
              </Link>
            ) : (
              <span className="text-foreground truncate font-medium">{entry.name}</span>
            )}
            {row.kind === 'own' ? (
              <Badge variant="status" value="info">
                You
              </Badge>
            ) : null}
          </span>
          {subtitle ? <span className="text-muted truncate text-xs">{subtitle}</span> : null}
        </div>
      </TableCell>
      <TableCell numeric className="text-secondary">
        {entry.mention_count}
      </TableCell>
      <TableCell numeric className="text-secondary">
        {formatPercent(entry.sov_share)}
      </TableCell>
      <TableCell numeric className="text-secondary">
        {formatPercent(entry.win_rate)}
      </TableCell>
      <TableCell>
        <RankDistributionBar distribution={entry.rank_distribution} />
      </TableCell>
      <TableCell numeric className="text-secondary">
        {formatAvgRank(entry.avg_rank)}
      </TableCell>
      <TableCell>
        <PriceRelationCell entry={entry} />
      </TableCell>
    </TableRow>
  );
}

/**
 * The Price relation cell: persisted match/higher/lower counts as labelled
 * badges (Match = success, Higher = warning, Lower = info). An analyzer-v1
 * row with persisted mismatches reads `Direction unavailable` with the muted
 * mismatch count — direction is NEVER inferred for v1 data. Nothing
 * verifiable renders the null placeholder.
 */
function PriceRelationCell({
  entry,
}: Readonly<{
  entry: ProductVisibilityEntry | CompetitorProductVisibilityEntry;
}>) {
  const display = priceRelationDisplay(entry);
  if (display.kind === 'empty') return <span className="text-subtle">—</span>;
  if (display.kind === 'unavailable') {
    return (
      <span className="flex items-center gap-2">
        <Badge variant="status" value="warning">
          Direction unavailable
        </Badge>
        <span className="text-muted mono text-xs">{display.mismatch}</span>
      </span>
    );
  }
  return (
    <span className="flex flex-wrap items-center gap-1">
      {display.match > 0 ? (
        <Badge variant="status" value="success">
          Match {display.match}
        </Badge>
      ) : null}
      {display.higher > 0 ? (
        <Badge variant="status" value="warning">
          Higher {display.higher}
        </Badge>
      ) : null}
      {display.lower > 0 ? (
        <Badge variant="status" value="info">
          Lower {display.lower}
        </Badge>
      ) : null}
    </span>
  );
}

/**
 * Compact stacked bar of the persisted rank buckets (Top 1 → 6+ → unranked).
 * Each segment carries a `title` with its bucket label + count so the value
 * is never color-only.
 */
function RankDistributionBar({ distribution }: Readonly<{ distribution: Record<string, number> }>) {
  const total = RANK_BUCKET_ORDER.reduce((sum, key) => sum + (distribution[key] ?? 0), 0);
  if (total === 0) return <span className="text-subtle">—</span>;
  return (
    <div
      className="bg-neutral-bg flex h-2 w-full overflow-hidden rounded-full"
      role="img"
      aria-label={RANK_BUCKET_ORDER.map(
        (key) => `${RANK_BUCKET_LABELS[key]}: ${distribution[key] ?? 0}`,
      ).join(', ')}
    >
      {RANK_BUCKET_ORDER.map((key) => {
        const count = distribution[key] ?? 0;
        if (count === 0) return null;
        return (
          <span
            key={key}
            title={`${RANK_BUCKET_LABELS[key]}: ${count}`}
            className={cn('h-full', RANK_SEGMENT_CLASS[key])}
            style={{ width: `${(count / total) * 100}%` }}
          />
        );
      })}
    </div>
  );
}

function VisibilitySkeleton() {
  return (
    <div className="grid gap-4" aria-hidden>
      <Skeleton className="h-8 w-96" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24 w-full" />
        ))}
      </div>
      <Skeleton className="h-56 w-full" />
    </div>
  );
}

/** Run picker shared by the toolbar and the selected-run 404 empty state. */
function RunSelectorDropdown({
  runOptions,
  activeRunId,
  selectRun,
}: Readonly<{
  runOptions: VisibilityQueries['runOptions'];
  activeRunId: string | null;
  selectRun: (id: string | null) => void;
}>) {
  const activeRun = runOptions.find((run) => run.id === activeRunId) ?? null;
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <Button variant="secondary" size="sm" aria-label="Select run">
          <span className="text-muted">Run:</span>
          <span className="font-medium">{activeRun?.label ?? 'Latest'}</span>
          <ChevronDown className="text-muted size-3" aria-hidden />
        </Button>
      </DropdownTrigger>
      <DropdownContent>
        <DropdownLabel>Runs</DropdownLabel>
        <DropdownRadioGroup value={activeRunId ?? '__latest__'}>
          <DropdownRadioItem value="__latest__" onSelect={() => selectRun(null)}>
            Latest
          </DropdownRadioItem>
          {runOptions.map((run) => (
            <DropdownRadioItem key={run.id} value={run.id} onSelect={() => selectRun(run.id)}>
              {run.label}
            </DropdownRadioItem>
          ))}
        </DropdownRadioGroup>
      </DropdownContent>
    </Dropdown>
  );
}

/** D2 state (a): no completed run has product metrics yet — guide to runs. */
function NoAuditEmpty({
  onGoToCatalog,
  selectedRun = false,
}: Readonly<{ onGoToCatalog: () => void; selectedRun?: boolean }>) {
  return (
    <EmptyState
      icon={Inbox}
      heading="No product visibility yet"
      description={
        selectedRun
          ? 'No product metrics in this run — pick another run, or launch one that scores your catalog.'
          : 'Run an audit to measure how answer engines rank and price your products — share of voice, rank distribution, and price accuracy appear here when it completes.'
      }
      action={
        <>
          <Button variant="ghost" size="md" onClick={onGoToCatalog}>
            <Package className="size-4" aria-hidden />
            Go to Catalog
          </Button>
          <Button asChild variant="primary" size="md">
            <Link href="/runs">View runs</Link>
          </Button>
        </>
      }
    />
  );
}

/**
 * D2 state (b): the selected run completed but recorded ZERO product
 * mentions in this slice (COM-1/COM-2). Explain why (the answers never
 * named a catalog product) and give the two concrete fixes — prompts that
 * name the products, and catalog aliases that match how people ask —
 * instead of the old wall of zeros.
 */
function NoMentionsEmpty({
  engineParam,
  surface,
  onGoToCatalog,
}: Readonly<{
  engineParam: string | undefined;
  surface: string;
  onGoToCatalog: () => void;
}>) {
  // Name the active slice so a filtered-to-zero view never reads as "the
  // whole run had nothing". BOTH filters are named when both are set — the
  // engine-only fallback silently dropped the surface, so a doubly-filtered
  // empty view under-reported why it was empty.
  const filters = [
    engineParam ? engineLabel(engineParam) : null,
    surface ? `the ${surface} surface` : null,
  ].filter((part): part is string => part !== null);
  const slice = filters.length > 0 ? ` on ${filters.join(' and ')}` : '';
  return (
    <EmptyState
      icon={Package}
      heading="This run recorded no product mentions"
      description={`The selected run completed, but none of its answers${slice} mentioned a product from your catalog.`}
      action={
        <>
          <Button asChild variant="primary" size="md">
            <Link href="/prompts">Add product-named prompts</Link>
          </Button>
          <Button variant="ghost" size="md" onClick={onGoToCatalog}>
            Check catalog aliases
          </Button>
        </>
      }
    />
  );
}
