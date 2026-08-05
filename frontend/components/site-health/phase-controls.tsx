'use client';

import { useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { eyebrowClasses } from '@/components/ui/eyebrow';
import { Input } from '@/components/ui/input';
import type { useSiteHealthScreen } from '@/lib/site-health/use-site-health-screen';
import type { PhaseRun, SiteCrawl } from '@/lib/api/types';
import { humanizeApiError } from '@/lib/api/errors';
import { SITE_HEALTH_DEFAULT_PHASE_BATCH_SIZE } from '@/lib/config/operational';

function positiveInteger(value: string): number | null {
  if (!/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

export type PhaseMutation = 'startDiscovery' | 'stopDiscovery' | 'startAnalysis' | 'stopAnalysis';

type SiteHealthScreen = ReturnType<typeof useSiteHealthScreen>;

function PhaseCounters({ counters }: Readonly<{ counters: SiteCrawl['counters'] }>) {
  const rows: ReadonlyArray<readonly [string, number | null]> = [
    ['Discovered', counters.discovered],
    ['Selected', counters.selected],
    ['Queued', counters.queued],
    ['Running', counters.running],
    ['Analyzed', counters.analyzed],
    ['Errors', counters.errors],
    ['Blocked', counters.blocked],
  ];

  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:col-span-2 lg:grid-cols-7">
      {rows.map(([label, value]) => (
        <div key={label} className="grid gap-0.5">
          <dt className="text-muted text-xs">{label}</dt>
          <dd className="mono text-foreground text-sm font-semibold">{value ?? '—'}</dd>
        </div>
      ))}
    </dl>
  );
}

function DiscoveryControl({
  screen,
  crawlId,
  phaseRun,
  running,
  onMutationStart,
}: Readonly<{
  screen: SiteHealthScreen;
  crawlId: string;
  phaseRun: PhaseRun | null | undefined;
  running: boolean;
  onMutationStart: (mutation: PhaseMutation) => void;
}>) {
  const [count, setCount] = useState(String(SITE_HEALTH_DEFAULT_PHASE_BATCH_SIZE));
  const batch = positiveInteger(count);

  const stop = () => {
    onMutationStart('stopDiscovery');
    screen.stopDiscoveryMutation.mutate(crawlId);
  };
  const start = () => {
    if (batch === null) return;
    onMutationStart('startDiscovery');
    screen.startDiscoveryMutation.mutate({
      crawlId,
      input: { additional_url_count: batch },
    });
  };

  return (
    <div className="grid gap-2">
      <div>
        <h3 className={eyebrowClasses}>URL discovery</h3>
        <p className="text-secondary text-sm">
          Add a new batch without resetting previously discovered URLs.
        </p>
        {phaseRun ? (
          <p className="text-muted text-xs">
            Current batch: {phaseRun.processed_count} of {phaseRun.requested_count} processed
          </p>
        ) : null}
      </div>
      <div className="flex items-end gap-2">
        <label className="grid min-w-0 flex-1 gap-1 text-sm font-medium">
          Additional URLs
          <Input
            type="number"
            inputMode="numeric"
            min={1}
            value={count}
            onChange={(event) => setCount(event.target.value)}
            aria-invalid={batch === null}
          />
        </label>
        {running ? (
          <Button
            variant="destructive"
            onClick={stop}
            disabled={screen.stopDiscoveryMutation.isPending}
          >
            {screen.stopDiscoveryMutation.isPending ? 'Stopping…' : 'Stop discovery'}
          </Button>
        ) : (
          <Button
            onClick={start}
            disabled={batch === null || screen.startDiscoveryMutation.isPending}
          >
            {screen.startDiscoveryMutation.isPending ? 'Starting…' : 'Continue discovery'}
          </Button>
        )}
      </div>
    </div>
  );
}

function AnalysisControl({
  screen,
  crawlId,
  phaseRun,
  running,
  selectedUrlIds,
  onMutationStart,
}: Readonly<{
  screen: SiteHealthScreen;
  crawlId: string;
  phaseRun: PhaseRun | null | undefined;
  running: boolean;
  selectedUrlIds: ReadonlySet<string>;
  onMutationStart: (mutation: PhaseMutation) => void;
}>) {
  const [count, setCount] = useState(String(SITE_HEALTH_DEFAULT_PHASE_BATCH_SIZE));
  const batch = positiveInteger(count);
  const selectionVersion = screen.monitoredQuery.data?.selection_version;
  const selectionTooLarge = batch !== null && selectedUrlIds.size > batch;

  const stop = () => {
    onMutationStart('stopAnalysis');
    screen.stopAnalysisMutation.mutate(crawlId);
  };
  const start = () => {
    if (batch === null || selectionVersion === undefined) return;
    onMutationStart('startAnalysis');
    screen.startAnalysisMutation.mutate({
      crawlId,
      input: {
        requested_url_count: batch,
        site_url_ids: [...selectedUrlIds],
        expected_selection_version: selectionVersion,
      },
    });
  };

  return (
    <div className="grid gap-2">
      <div>
        <h3 className={eyebrowClasses}>URL analysis</h3>
        <p className="text-secondary text-sm">
          Analyze checked URLs first, then fill the batch with highest-value pages.
        </p>
        {phaseRun ? (
          <p className="text-muted text-xs">
            Current batch: {phaseRun.processed_count} of {phaseRun.requested_count} processed
          </p>
        ) : null}
      </div>
      <div className="flex items-end gap-2">
        <label className="grid min-w-0 flex-1 gap-1 text-sm font-medium">
          URLs to analyze
          <Input
            type="number"
            inputMode="numeric"
            min={1}
            value={count}
            onChange={(event) => setCount(event.target.value)}
            aria-invalid={batch === null || selectionTooLarge}
          />
        </label>
        {running ? (
          <Button
            variant="destructive"
            onClick={stop}
            disabled={screen.stopAnalysisMutation.isPending}
          >
            {screen.stopAnalysisMutation.isPending ? 'Stopping…' : 'Stop analysis'}
          </Button>
        ) : (
          <Button
            onClick={start}
            disabled={
              batch === null ||
              selectionTooLarge ||
              selectionVersion === undefined ||
              screen.startAnalysisMutation.isPending
            }
          >
            {screen.startAnalysisMutation.isPending ? 'Starting…' : 'Start analysis'}
          </Button>
        )}
      </div>
      {selectedUrlIds.size > 0 ? (
        <p className="text-muted text-xs">{selectedUrlIds.size} checked URLs selected.</p>
      ) : null}
      {selectionTooLarge ? (
        <Alert tone="warning">Increase the analysis batch to include every checked URL.</Alert>
      ) : null}
    </div>
  );
}

export function PhaseControls({
  screen,
  selectedUrlIds,
  lastMutation,
  onMutationStart,
}: Readonly<{
  screen: SiteHealthScreen;
  selectedUrlIds: ReadonlySet<string>;
  lastMutation: PhaseMutation | null;
  onMutationStart: (mutation: PhaseMutation) => void;
}>) {
  const crawl = screen.crawl;
  const phaseRuns = screen.dashboardQuery.data?.phase_runs;
  const discoveryRunning =
    crawl?.discovery_status === 'running' || phaseRuns?.discovery?.status === 'running';
  const analysisRunning =
    crawl?.analysis_status === 'running' || phaseRuns?.analysis?.status === 'running';

  if (!crawl || !screen.entitlementQuery.data?.advanced_controls_enabled) return null;

  const mutationErrors = {
    startDiscovery: screen.startDiscoveryMutation.error,
    stopDiscovery: screen.stopDiscoveryMutation.error,
    startAnalysis: screen.startAnalysisMutation.error,
    stopAnalysis: screen.stopAnalysisMutation.error,
  };
  const mutationError = lastMutation ? mutationErrors[lastMutation] : null;
  const mutationMessage = mutationError
    ? humanizeApiError(mutationError, 'The phase could not be updated.').message
    : null;

  return (
    <Card data-testid="site-health-phase-controls">
      <CardContent className="grid gap-4 lg:grid-cols-2">
        <PhaseCounters counters={crawl.counters} />
        <DiscoveryControl
          screen={screen}
          crawlId={crawl.id}
          phaseRun={phaseRuns?.discovery}
          running={discoveryRunning}
          onMutationStart={onMutationStart}
        />
        <AnalysisControl
          screen={screen}
          crawlId={crawl.id}
          phaseRun={phaseRuns?.analysis}
          running={analysisRunning}
          selectedUrlIds={selectedUrlIds}
          onMutationStart={onMutationStart}
        />

        {mutationMessage ? (
          <div className="lg:col-span-2">
            <Alert tone="danger">{mutationMessage}</Alert>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
