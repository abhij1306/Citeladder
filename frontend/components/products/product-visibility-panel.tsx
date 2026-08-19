'use client';

import { useState } from 'react';
import { Download, RefreshCw } from 'lucide-react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardEyebrow } from '@/components/ui/card';
import { displayHeadingLgClasses } from '@/components/ui/typography';
import { ApiError } from '@/lib/api/errors';
import { productsApi } from '@/lib/api/products';

import {
  VISIBILITY_SUB_TABS,
  aggregateAttributeFrequency,
  aggregateBuyerDestinationMix,
  buildCoPlacementMatrix,
  hasDirectionUnavailableRows,
  formatAvgRank,
  formatPercent,
  summarizeProductVisibility,
  type VisibilitySubTab,
} from '@/lib/products/catalog';
import type { useProductVisibilityQueries } from '@/lib/products/use-products-screen';

import { AttributeFrequencyPanel } from './attribute-frequency-panel';
import { BuyerDestinationBreakdown } from './buyer-destination-breakdown';
import { CompetitorCoPlacementMatrix } from './competitor-co-placement-matrix';
import { EngineFilterDropdown } from './engine-filter-dropdown';
import { NestedTabs } from '@/components/ui/nested-tabs';
import { SurfaceFilterDropdown } from './surface-filter-dropdown';
import {
  NoAuditEmpty,
  NoMentionsEmpty,
  RankingsCard,
  RunSelectorDropdown,
  SummaryCard,
  VisibilitySkeleton,
} from './product-visibility-view';

type VisibilityQueries = ReturnType<typeof useProductVisibilityQueries>;

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
