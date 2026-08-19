'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { RUN_ACTIVE_POLL_MS } from '@/lib/config/runs';
import { useRunEvents } from '@/lib/runs/use-run-events';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { useState } from 'react';

import { ExecutionEvidenceDrawer } from '@/components/runs/execution-evidence-drawer';
import { RunDetailView } from '@/components/runs/run-detail-view';
import { queryKeys } from '@/lib/api/query-keys';
import { mutationNoticeForError } from '@/lib/api/mutation-notice';
import { runsApi } from '@/lib/api/runs';
import { shouldPollAudit } from '@/lib/runs/status';

/** Poll interval (ms) while a run is active. Polling is the baseline; SSE is optional. */
// Cadences live in config, not here (invariant 1).
const POLL_INTERVAL_MS = RUN_ACTIVE_POLL_MS;

/**
 * Run detail screen (F10, design.md §9.7).
 *
 * A progress panel (status + requested/completed/failed counts + cancel +
 * CSV/MD export links) over an executions table. Progress is POLLING-FIRST: the
 * audit + executions queries refetch on an interval while the run is active and
 * stop once it terminalizes. (SSE via `/events?stream=true` is an optional
 * enhancement per the plan; polling is the reliable baseline.)
 */
export default function RunDetailPage() {
  const params = useParams<{ runId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const runId = params.runId;
  const queryClient = useQueryClient();
  const executionParam = searchParams.get('execution');
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(null);

  const auditQuery = useQuery({
    queryKey: queryKeys.runs.detail(runId),
    queryFn: ({ signal }) => runsApi.getAudit(runId, { signal }),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && shouldPollAudit(status) ? POLL_INTERVAL_MS : false;
    },
  });

  const active = auditQuery.data ? shouldPollAudit(auditQuery.data.status) : false;

  const executionsQuery = useQuery({
    queryKey: queryKeys.runs.executions(runId),
    queryFn: ({ signal }) => runsApi.listExecutions(runId, { signal }),
    refetchInterval: active ? POLL_INTERVAL_MS : false,
  });

  // Stream is the accelerator; the polling above stays the baseline, so a
  // dropped stream never stalls the run.
  useRunEvents(runId, auditQuery.data?.project_id, active);

  const cancelMutation = useMutation({
    mutationFn: () => runsApi.cancelAudit(runId),
    onSuccess: (audit) => {
      queryClient.setQueryData(queryKeys.runs.detail(runId), audit);
      queryClient.invalidateQueries({ queryKey: queryKeys.runs.executions(runId) });
      // A cancel changes the run's status, so the runs list and any
      // status-dependent visibility view are now stale — refetch both.
      queryClient.invalidateQueries({ queryKey: queryKeys.runs.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.visibility.all });
    },
  });
  const rerunFailuresMutation = useMutation({
    mutationFn: () => runsApi.rerunFailures(runId),
    onSuccess: (repairAudit) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.runs.all });
      router.push(`/runs/${repairAudit.id}`);
    },
  });

  const executions = executionsQuery.data ?? [];
  // The ?execution= URL param takes priority only while it matches a real
  // execution; a stale/unknown id must not mask an in-table selection.
  const activeExecutionId = executions.some((execution) => execution.id === executionParam)
    ? executionParam
    : selectedExecutionId;
  const selectedExecution =
    executions.find((execution) => execution.id === activeExecutionId) ?? null;

  return (
    <>
      <RunDetailView
        audit={auditQuery.data}
        auditLoading={auditQuery.isLoading}
        auditError={auditQuery.isError ? auditQuery.error : null}
        executions={executionsQuery.data}
        executionsLoading={executionsQuery.isLoading}
        executionsError={executionsQuery.isError}
        cancelPending={cancelMutation.isPending}
        cancelNotice={
          cancelMutation.isError
            ? mutationNoticeForError(cancelMutation.error, { action: 'cancel the run' })
            : null
        }
        rerunPending={rerunFailuresMutation.isPending}
        rerunNotice={
          rerunFailuresMutation.isError
            ? mutationNoticeForError(rerunFailuresMutation.error, {
                action: 'rerun failed executions',
              })
            : null
        }
        onCancel={() => cancelMutation.mutate()}
        onRerunFailures={() => rerunFailuresMutation.mutate()}
        onSelectEvidence={(execution) => setSelectedExecutionId(execution.id)}
      />
      <ExecutionEvidenceDrawer
        execution={selectedExecution}
        open={selectedExecution !== null}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedExecutionId(null);
            if (searchParams.has('execution')) router.replace(`/runs/${runId}`);
          }
        }}
      />
    </>
  );
}
