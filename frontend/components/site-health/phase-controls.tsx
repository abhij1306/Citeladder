'use client';

import { useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import type { useSiteHealthScreen } from '@/lib/site-health/use-site-health-screen';
import type { PhaseRun, SiteCrawl } from '@/lib/api/types';
import { humanizeApiError } from '@/lib/api/errors';
import { SITE_HEALTH_DEFAULT_PHASE_BATCH_SIZE } from '@/lib/config/operational';
import { cn } from '@/lib/utils';

function positiveInteger(value: string): number | null {
  if (!/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

export type PhaseMutation = 'startDiscovery' | 'stopDiscovery' | 'startAnalysis' | 'stopAnalysis';

type SiteHealthScreen = ReturnType<typeof useSiteHealthScreen>;

function PhaseCounters({ counters }: Readonly<{ counters: SiteCrawl['counters'] }>) {
  const problems = counters.errors + counters.blocked;
  const rows: ReadonlyArray<readonly [string, number | null, string?]> = [
    ['found', counters.discovered],
    ['selected', counters.selected],
    ['analyzed', counters.analyzed],
    ['problems', problems, problems > 0 ? 'text-danger-text' : undefined],
  ];

  return (
    <dl className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
      {rows.map(([label, value, className]) => (
        <div key={label} className="flex items-baseline gap-1">
          <dd className={cn('mono text-foreground text-sm font-semibold', className)}>
            {value ?? '—'}
          </dd>
          <dt className="text-muted text-xs">{label}</dt>
        </div>
      ))}
    </dl>
  );
}

function BatchProgress({ phaseRun }: Readonly<{ phaseRun: PhaseRun | null | undefined }>) {
  if (!phaseRun) return <span className="text-muted text-xs">Ready</span>;
  return (
    <span className="text-muted text-xs">
      {phaseRun.processed_count}/{phaseRun.requested_count} processed
    </span>
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
  const starting = screen.startDiscoveryMutation.isPending;
  const stopping = screen.stopDiscoveryMutation.isPending;

  const stop = () => {
    if (stopping) return;
    onMutationStart('stopDiscovery');
    screen.stopDiscoveryMutation.mutate(crawlId);
  };
  const start = () => {
    if (batch === null || starting) return;
    onMutationStart('startDiscovery');
    screen.startDiscoveryMutation.mutate({
      crawlId,
      input: { additional_url_count: batch },
    });
  };

  return (
    <section className="grid gap-2" aria-labelledby="discovery-control-title">
      <div className="flex items-baseline justify-between gap-3">
        <h3 id="discovery-control-title" className="text-foreground text-sm font-semibold">
          Discover more URLs
        </h3>
        <BatchProgress phaseRun={phaseRun} />
      </div>
      <div className="flex items-center gap-2">
        <label className="min-w-0 flex-1">
          <span className="sr-only">Additional URLs</span>
          <Input
            type="number"
            inputMode="numeric"
            min={1}
            value={count}
            onChange={(event) => setCount(event.target.value)}
            aria-invalid={batch === null}
            disabled={running || starting || stopping}
          />
        </label>
        {running ? (
          <Button
            className="min-w-36 shrink-0"
            variant="destructive"
            onClick={stop}
            disabled={stopping || starting}
          >
            {stopping ? 'Stopping…' : 'Stop discovery'}
          </Button>
        ) : (
          <Button
            className="min-w-36 shrink-0"
            onClick={start}
            disabled={batch === null || starting || stopping}
          >
            {starting ? 'Starting…' : 'Continue discovery'}
          </Button>
        )}
      </div>
    </section>
  );
}

function AnalysisControl({
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
  const selectionVersion = screen.monitoredQuery.data?.selection_version;
  const starting = screen.startAnalysisMutation.isPending;
  const stopping = screen.stopAnalysisMutation.isPending;

  const stop = () => {
    if (stopping) return;
    onMutationStart('stopAnalysis');
    screen.stopAnalysisMutation.mutate(crawlId);
  };
  const start = () => {
    if (batch === null || selectionVersion === undefined || starting) return;
    onMutationStart('startAnalysis');
    screen.startAnalysisMutation.mutate({
      crawlId,
      input: {
        requested_url_count: batch,
        // No explicit id list: the batch analyzes the next `batch` monitored
        // URLs the server has not reached yet. Hand-picking rows was only
        // reachable from the page-kind accordion, which is gone.
        site_url_ids: [],
        expected_selection_version: selectionVersion,
      },
    });
  };

  return (
    <section className="grid gap-2" aria-labelledby="analysis-control-title">
      <div className="flex items-baseline justify-between gap-3">
        <h3 id="analysis-control-title" className="text-foreground text-sm font-semibold">
          Analyze URLs
        </h3>
        <BatchProgress phaseRun={phaseRun} />
      </div>
      <div className="flex items-center gap-2">
        <label className="min-w-0 flex-1">
          <span className="sr-only">URLs to analyze</span>
          <Input
            type="number"
            inputMode="numeric"
            min={1}
            value={count}
            onChange={(event) => setCount(event.target.value)}
            aria-invalid={batch === null}
            disabled={running || starting || stopping}
          />
        </label>
        {running ? (
          <Button
            className="min-w-36 shrink-0"
            variant="destructive"
            onClick={stop}
            disabled={stopping || starting}
          >
            {stopping ? 'Stopping…' : 'Stop analysis'}
          </Button>
        ) : (
          <Button
            className="min-w-36 shrink-0"
            onClick={start}
            disabled={batch === null || selectionVersion === undefined || starting || stopping}
          >
            {starting ? 'Starting…' : 'Start analysis'}
          </Button>
        )}
      </div>
    </section>
  );
}

export function PhaseControls({
  screen,
  lastMutation,
  onMutationStart,
  onRecrawl,
}: Readonly<{
  screen: SiteHealthScreen;
  lastMutation: PhaseMutation | null;
  onMutationStart: (mutation: PhaseMutation) => void;
  onRecrawl: () => void;
}>) {
  const crawl = screen.crawl;
  const phaseRuns = screen.dashboardQuery.data?.phase_runs;
  const discoveryRunning =
    crawl?.discovery_status === 'running' || phaseRuns?.discovery?.status === 'running';
  const analysisRunning =
    crawl?.analysis_status === 'running' || phaseRuns?.analysis?.status === 'running';

  // Only "there is no crawl yet" hides these controls. They used to also be
  // gated on `advanced_controls_enabled`, which defaulted off — so continuing
  // discovery and starting an analysis batch, the two things this screen
  // exists to do, were absent with no explanation. See the note on
  // `advanced_controls_enabled` in backend config/site_health.py.
  if (!crawl) return null;

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
  const phaseMutationPending =
    screen.startDiscoveryMutation.isPending ||
    screen.stopDiscoveryMutation.isPending ||
    screen.startAnalysisMutation.isPending ||
    screen.stopAnalysisMutation.isPending;

  return (
    <Card data-testid="site-health-phase-controls">
      <CardContent className="grid gap-3 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-foreground text-sm font-semibold">Crawl controls</h2>
          <div className="flex flex-wrap items-center justify-end gap-3">
            <PhaseCounters counters={crawl.counters} />
            <Button
              size="sm"
              variant="secondary"
              onClick={onRecrawl}
              disabled={screen.active || screen.startPending || phaseMutationPending}
            >
              {screen.startPending ? 'Starting…' : 'Re-crawl site'}
            </Button>
          </div>
        </div>
        <div className="border-border-subtle grid gap-4 border-t pt-3 lg:grid-cols-2 lg:gap-6">
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
            onMutationStart={onMutationStart}
          />
        </div>
        {mutationMessage ? <Alert tone="danger">{mutationMessage}</Alert> : null}
      </CardContent>
    </Card>
  );
}
