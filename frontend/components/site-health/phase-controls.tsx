'use client';

import { useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { eyebrowClasses } from '@/components/ui/eyebrow';
import { Input } from '@/components/ui/input';
import type { useSiteHealthScreen } from '@/lib/site-health/use-site-health-screen';
import { humanizeApiError } from '@/lib/api/errors';
import { SITE_HEALTH_DEFAULT_PHASE_BATCH_SIZE } from '@/lib/config/operational';

function positiveInteger(value: string): number | null {
  if (!/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

type PhaseMutation = 'startDiscovery' | 'stopDiscovery' | 'startAnalysis' | 'stopAnalysis';

export function PhaseControls({
  screen,
  selectedUrlIds,
}: Readonly<{
  screen: ReturnType<typeof useSiteHealthScreen>;
  selectedUrlIds: ReadonlySet<string>;
}>) {
  const defaultBatchSize = String(SITE_HEALTH_DEFAULT_PHASE_BATCH_SIZE);
  const [discoveryCount, setDiscoveryCount] = useState(defaultBatchSize);
  const [analysisCount, setAnalysisCount] = useState(defaultBatchSize);
  const [lastMutation, setLastMutation] = useState<PhaseMutation | null>(null);
  const crawl = screen.crawl;
  const selectionVersion = screen.monitoredQuery.data?.selection_version;
  const discoveryBatch = positiveInteger(discoveryCount);
  const analysisBatch = positiveInteger(analysisCount);
  const selectionTooLarge = analysisBatch !== null && selectedUrlIds.size > analysisBatch;
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
  const counterRows: ReadonlyArray<readonly [string, number | null]> = [
    ['Discovered', crawl.counters.discovered],
    ['Selected', crawl.counters.selected],
    ['Queued', crawl.counters.queued],
    ['Running', crawl.counters.running],
    ['Analyzed', crawl.counters.analyzed],
    ['Errors', crawl.counters.errors],
    ['Blocked', crawl.counters.blocked],
  ];

  return (
    <Card data-testid="site-health-phase-controls">
      <CardContent className="grid gap-4 lg:grid-cols-2">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:col-span-2 lg:grid-cols-7">
          {counterRows.map(([label, value]) => (
            <div key={label} className="grid gap-0.5">
              <dt className="text-muted text-xs">{label}</dt>
              <dd className="mono text-foreground text-sm font-semibold">{value ?? '—'}</dd>
            </div>
          ))}
        </dl>
        <div className="grid gap-2">
          <div>
            <h3 className={eyebrowClasses}>URL discovery</h3>
            <p className="text-secondary text-sm">
              Add a new batch without resetting previously discovered URLs.
            </p>
            {phaseRuns?.discovery ? (
              <p className="text-muted text-xs">
                Current batch: {phaseRuns.discovery.processed_count} of{' '}
                {phaseRuns.discovery.requested_count} processed
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
                value={discoveryCount}
                onChange={(event) => setDiscoveryCount(event.target.value)}
                aria-invalid={discoveryBatch === null}
              />
            </label>
            {discoveryRunning ? (
              <Button
                variant="destructive"
                onClick={() => {
                  setLastMutation('stopDiscovery');
                  screen.stopDiscoveryMutation.mutate(crawl.id);
                }}
                disabled={screen.stopDiscoveryMutation.isPending}
              >
                {screen.stopDiscoveryMutation.isPending ? 'Stopping…' : 'Stop discovery'}
              </Button>
            ) : (
              <Button
                onClick={() => {
                  if (discoveryBatch === null) return;
                  setLastMutation('startDiscovery');
                  screen.startDiscoveryMutation.mutate({
                    crawlId: crawl.id,
                    input: { additional_url_count: discoveryBatch },
                  });
                }}
                disabled={discoveryBatch === null || screen.startDiscoveryMutation.isPending}
              >
                {screen.startDiscoveryMutation.isPending ? 'Starting…' : 'Continue discovery'}
              </Button>
            )}
          </div>
        </div>

        <div className="grid gap-2">
          <div>
            <h3 className={eyebrowClasses}>URL analysis</h3>
            <p className="text-secondary text-sm">
              Analyze checked URLs first, then fill the batch with highest-value pages.
            </p>
            {phaseRuns?.analysis ? (
              <p className="text-muted text-xs">
                Current batch: {phaseRuns.analysis.processed_count} of{' '}
                {phaseRuns.analysis.requested_count} processed
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
                value={analysisCount}
                onChange={(event) => setAnalysisCount(event.target.value)}
                aria-invalid={analysisBatch === null || selectionTooLarge}
              />
            </label>
            {analysisRunning ? (
              <Button
                variant="destructive"
                onClick={() => {
                  setLastMutation('stopAnalysis');
                  screen.stopAnalysisMutation.mutate(crawl.id);
                }}
                disabled={screen.stopAnalysisMutation.isPending}
              >
                {screen.stopAnalysisMutation.isPending ? 'Stopping…' : 'Stop analysis'}
              </Button>
            ) : (
              <Button
                onClick={() => {
                  if (analysisBatch === null || selectionVersion === undefined) return;
                  setLastMutation('startAnalysis');
                  screen.startAnalysisMutation.mutate({
                    crawlId: crawl.id,
                    input: {
                      requested_url_count: analysisBatch,
                      site_url_ids: [...selectedUrlIds],
                      expected_selection_version: selectionVersion,
                    },
                  });
                }}
                disabled={
                  analysisBatch === null ||
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

        {mutationMessage ? (
          <div className="lg:col-span-2">
            <Alert tone="danger">{mutationMessage}</Alert>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
