import { useEffect, useState } from 'react';
import { useMutation, useQueries, useQueryClient } from '@tanstack/react-query';

import { integrationsApi, type IntegrationSyncRun } from '@/lib/api/integrations';
import { queryKeys } from '@/lib/api/query-keys';
import { trafficApi, type TrafficSyncEnqueueResponse } from '@/lib/api/traffic';
import {
  isActiveSyncRun,
  isSucceededSyncRun,
  SYNC_RUN_POLL_MS,
} from '@/lib/integrations/sync-runs';

export function useTrafficSync(projectId: string | null) {
  const queryClient = useQueryClient();
  const [runs, setRuns] = useState<TrafficSyncEnqueueResponse>([]);
  const [startedAt, setStartedAt] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () => trafficApi.syncNow(projectId ?? ''),
    onSuccess: (enqueued) => {
      if (!enqueued.length) {
        setNotice(
          'No active mapped sync connection — connect and map one in Settings to start syncing.',
        );
        return;
      }
      setNotice(null);
      setRuns(enqueued);
      setStartedAt(new Date().toISOString());
    },
  });
  const runQueries = useQueries({
    queries: runs.map((run) => ({
      queryKey: queryKeys.integrations.sync(run.connection_id, run.sync_run_id),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        integrationsApi.getSync(run.connection_id, run.sync_run_id, { signal }),
      refetchInterval: (query: { state: { data?: IntegrationSyncRun } }) => {
        const result = query.state.data;
        return !result || isActiveSyncRun(result.status) ? SYNC_RUN_POLL_MS : false;
      },
    })),
  });
  const enqueued = runs.length > 0;
  const allTerminal =
    enqueued &&
    runQueries.every((query) => query.data !== undefined && !isActiveSyncRun(query.data.status));
  const syncing = enqueued && !allTerminal;
  const outcome = !allTerminal
    ? null
    : runQueries.every((query) => query.data && isSucceededSyncRun(query.data.status))
      ? 'succeeded'
      : 'failed';

  useEffect(() => {
    if (!allTerminal) return;
    void queryClient.invalidateQueries({ queryKey: queryKeys.traffic.all });
    void queryClient.invalidateQueries({ queryKey: queryKeys.integrations.all });
  }, [allTerminal, queryClient]);

  return { mutation, notice, outcome, startedAt, syncing };
}
