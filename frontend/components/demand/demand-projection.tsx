'use client';

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Calendar, Loader2, RefreshCw, Search, Sparkles, X } from 'lucide-react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { FilterChip } from '@/components/ui/filter-chip';
import { Input } from '@/components/ui/input';
import { MutationNotice } from '@/components/ui/mutation-notice';
import { Skeleton } from '@/components/ui/skeleton';
import { DemandDetectorBar } from '@/components/demand/demand-detector-bar';
import { DemandEvidenceDrawer } from '@/components/demand/demand-evidence-drawer';
import { DemandSignalCard } from '@/components/demand/demand-signal-card';
import { DemandSummaryCards } from '@/components/demand/demand-summary-cards';
import { demandApi, type DemandSignal, type DemandSnapshot } from '@/lib/api/demand';
import { httpErrorStatus } from '@/lib/api/errors';
import { mutationNoticeForError } from '@/lib/api/mutation-notice';
import {
  countByTab,
  FILTER_TABS,
  matchesTab,
  signalTarget,
  type FilterTab,
} from '@/lib/demand/signals';
import { formatWindowDate } from '@/lib/format';
import { useProjectContext } from '@/lib/project/project-context';

function DemandProjectionSkeleton() {
  return (
    <div className="grid gap-[var(--workspace-gap)]" aria-busy="true">
      <output className="sr-only">Loading search demand</output>
      {/* Header skeleton */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="grid gap-1">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-96 max-w-full" />
        </div>
        <Skeleton className="h-9 w-32" />
      </div>

      {/* Summary Cards Skeleton */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-24 rounded-md" />
        ))}
      </div>

      {/* Detector Bar Skeleton */}
      <Skeleton className="h-12 rounded-md" />

      {/* Filter Bar Skeleton */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-7 w-24 rounded-full" />
          ))}
        </div>
        <Skeleton className="h-8 w-64" />
      </div>

      {/* Signal Cards Skeleton */}
      <div className="grid gap-3">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-40 rounded-md" />
        ))}
      </div>
    </div>
  );
}

function SearchDemandView({ snapshot }: Readonly<{ snapshot: DemandSnapshot }>) {
  const { activeProject } = useProjectContext();
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState<FilterTab>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedSignal, setSelectedSignal] = useState<DemandSignal | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  /**
   * Recompute is a QUEUED job, not a synchronous rebuild: the endpoint returns
   * 202 with `status: queued` and a worker produces the new snapshot later.
   * Refetching on success would therefore just re-read the current snapshot
   * and look like a no-op, so we report that the work was queued and let the
   * user refresh once it lands.
   */
  const recomputeMutation = useMutation({
    mutationFn: () =>
      demandApi.recompute(activeProject!.id, {
        window_start: snapshot.window_start,
        window_end: snapshot.window_end,
      }),
  });

  const refreshSnapshot = () =>
    queryClient.invalidateQueries({ queryKey: ['demand', activeProject?.id, 'latest'] });

  const handleInspect = (signal: DemandSignal) => {
    setSelectedSignal(signal);
    setDrawerOpen(true);
  };

  const windowLabel = `${formatWindowDate(snapshot.window_start)} – ${formatWindowDate(snapshot.window_end)}`;

  // Counts for every tab in one pass, recomputed only when the snapshot does —
  // not on every keystroke in the search box.
  const tabCounts = useMemo(
    () => new Map(FILTER_TABS.map(({ tab }) => [tab, countByTab(snapshot.signals, tab)] as const)),
    [snapshot.signals],
  );

  /**
   * The API returns signals ordered by priority, so a signal's rank is its
   * index in the FULL list. Pairing it here keeps the rank stable when a
   * filter hides the signals above it.
   */
  const filteredSignals = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return snapshot.signals
      .map((signal, index) => ({ signal, rank: index + 1 }))
      .filter(({ signal }) => {
        if (!matchesTab(signal, activeTab)) return false;
        if (!query) return true;
        const haystack = [
          signalTarget(signal),
          signal.page_url,
          signal.signal_type.replace(/_/g, ' '),
        ]
          .join(' ')
          .toLowerCase();
        return haystack.includes(query);
      });
  }, [snapshot.signals, activeTab, searchQuery]);

  return (
    <div className="grid gap-[var(--workspace-gap)]">
      {/* Top Header & Recompute Bar */}
      <div className="border-border-subtle flex flex-col gap-3 border-b pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="grid gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-foreground font-display text-xl font-bold">
              {snapshot.signals.length === 1
                ? '1 demand signal observed'
                : `${snapshot.signals.length} demand signals observed`}
            </h1>
            <span className="text-muted hidden sm:inline">•</span>
            <span className="text-muted inline-flex items-center gap-1 text-xs">
              <Calendar className="size-3.5" aria-hidden="true" />
              {windowLabel}
            </span>
          </div>
          <p className="text-secondary text-xs">
            Versioned GSC query evidence. Highest-priority signals are shown first; branded demand
            remains a separate cohort.
          </p>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => recomputeMutation.mutate()}
            disabled={recomputeMutation.isPending}
            className="shrink-0 text-xs"
          >
            {recomputeMutation.isPending ? (
              <>
                <Loader2 className="mr-1.5 size-3.5 animate-spin" />
                Queueing…
              </>
            ) : (
              <>
                <RefreshCw className="mr-1.5 size-3.5" />
                Recompute Signals
              </>
            )}
          </Button>
        </div>
      </div>

      {recomputeMutation.isError ? (
        <MutationNotice
          notice={mutationNoticeForError(recomputeMutation.error, {
            action: 'queue the search demand recompute',
          })}
          onRetry={() => recomputeMutation.mutate()}
        />
      ) : null}

      {recomputeMutation.isSuccess ? (
        <Alert tone="info">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span>
              {recomputeMutation.data.status === 'already_queued'
                ? 'A recompute for this window is already queued.'
                : 'Recompute queued. Signals refresh once the job finishes.'}
            </span>
            <Button type="button" variant="ghost" size="sm" onClick={() => refreshSnapshot()}>
              Check for the new snapshot
            </Button>
          </div>
        </Alert>
      ) : null}

      {/* Summary KPI Strip */}
      <DemandSummaryCards snapshot={snapshot} />

      {/* Detector Status Ribbon */}
      <DemandDetectorBar snapshot={snapshot} />

      {/* Interactive Filter & Search Controls */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-1.5">
          {FILTER_TABS.map(({ tab, label }) => {
            const count = tabCounts.get(tab) ?? 0;
            // The optional cohorts stay hidden while empty, but a tab the user
            // has already selected must remain visible to switch away from.
            const optional = tab === 'trends' || tab === 'branded';
            if (optional && count === 0 && activeTab !== tab) return null;
            return (
              <FilterChip
                key={tab}
                active={activeTab === tab}
                onClick={() => setActiveTab(tab)}
                count={count}
              >
                {label}
              </FilterChip>
            );
          })}
        </div>

        {/* Search Input */}
        <div className="relative w-full sm:w-64">
          <Search className="text-muted pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Filter queries or URLs..."
            className="pr-8 pl-8 text-xs"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery('')}
              className="text-muted hover:text-foreground absolute top-1/2 right-2.5 -translate-y-1/2"
              aria-label="Clear filter search"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Signals List Feed */}
      {filteredSignals.length > 0 ? (
        <div className="grid gap-3">
          {filteredSignals.map(({ signal, rank }) => (
            <DemandSignalCard
              key={signal.id}
              signal={signal}
              rank={rank}
              onInspect={handleInspect}
            />
          ))}
        </div>
      ) : snapshot.signals.length === 0 ? (
        <div className="bg-panel border-border rounded-md border p-[var(--empty-state-padding)] text-center">
          <Sparkles className="text-muted/60 mx-auto size-8" />
          <h3 className="text-foreground mt-2 text-sm font-semibold">
            No qualifying search gaps observed
          </h3>
          <p className="text-muted mt-1 text-xs">
            Search Console data was observed, but no configured detector emitted a signal in this
            window.
          </p>
        </div>
      ) : (
        <div className="bg-panel border-border rounded-md border p-[var(--empty-state-padding)] text-center">
          <Search className="text-muted/60 mx-auto size-8" />
          <h3 className="text-foreground mt-2 text-sm font-semibold">
            No signals match your filter
          </h3>
          <p className="text-muted mt-1 text-xs">
            Try choosing a different filter tab or clearing your search term.
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setActiveTab('all');
              setSearchQuery('');
            }}
            className="mt-3 text-xs"
          >
            Clear Filters
          </Button>
        </div>
      )}

      {/* Evidence Inspection Drawer */}
      <DemandEvidenceDrawer
        signal={selectedSignal}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />
    </div>
  );
}

export function DemandProjection() {
  const { activeProject, isLoading: projectLoading } = useProjectContext();
  const latest = useQuery({
    queryKey: ['demand', activeProject?.id, 'latest'],
    queryFn: ({ signal }) => demandApi.getLatest(activeProject!.id, { signal }),
    enabled: Boolean(activeProject),
  });

  if (projectLoading || latest.isLoading) {
    return <DemandProjectionSkeleton />;
  }
  if (!activeProject) {
    return <Alert tone="info">Select a project to inspect search demand.</Alert>;
  }
  if (latest.isError && httpErrorStatus(latest.error) === 404) {
    return (
      <Alert tone="info">
        No Search Demand snapshot exists yet. Sync Traffic evidence, then recompute Search Demand.
      </Alert>
    );
  }
  if (latest.isError) {
    return <Alert tone="danger">Search demand could not be loaded.</Alert>;
  }
  if (!latest.data) return null;

  if (latest.data.coverage.search !== 'observed') {
    return (
      <Alert tone="info">
        Search Console evidence is unavailable for this snapshot. Sync Search Console to measure
        search demand.
      </Alert>
    );
  }

  // The route already wraps this subtree in a TooltipProvider.
  return <SearchDemandView snapshot={latest.data} />;
}
