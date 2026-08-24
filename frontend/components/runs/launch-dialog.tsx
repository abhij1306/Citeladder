'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import { mutationNoticeForError } from '@/lib/api/mutation-notice';
import { promptsApi } from '@/lib/api/prompts';
import { providersApi } from '@/lib/api/providers';
import { queryKeys } from '@/lib/api/query-keys';
import { runsApi } from '@/lib/api/runs';
import type { Audit, LogicalEngine } from '@/lib/api/types';
import { ENGINE_ORDER, isConfigured, isVerified } from '@/lib/providers/catalog';
import { buildLaunchPayload, canLaunch, DEFAULT_REPETITIONS } from '@/lib/runs/launch';

import { LaunchDialogView } from './launch-dialog-view';

function availableEngines(
  connections: Awaited<ReturnType<typeof providersApi.listConnections>> | undefined,
) {
  const verified = new Set<LogicalEngine>();
  const stored = new Set<LogicalEngine>();
  for (const connection of connections ?? []) {
    if (!isConfigured(connection)) continue;
    const target = isVerified(connection) ? verified : stored;
    for (const route of connection.routes ?? []) target.add(route.logical_engine);
  }
  return {
    configuredEngines: ENGINE_ORDER.filter((engine) => verified.has(engine)),
    unverifiedEngines: ENGINE_ORDER.filter((engine) => stored.has(engine) && !verified.has(engine)),
  };
}

/** Launch controller: queries, mutations, and form selection stay here; UI is in the view. */
export function LaunchDialog({
  open,
  onOpenChange,
  projectId,
  onLaunched,
  fixedPromptSetId,
  auditScope = 'brand',
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  onLaunched?: (audit: Audit) => void;
  fixedPromptSetId?: string;
  auditScope?: 'brand' | 'commerce';
}>) {
  const queryClient = useQueryClient();
  const promptSetsQuery = useQuery({
    queryKey: queryKeys.prompts.sets(projectId),
    queryFn: ({ signal }) => promptsApi.listPromptSets(projectId, { signal }),
    enabled: open,
  });
  const connectionsQuery = useQuery({
    queryKey: queryKeys.providers.connections(),
    queryFn: ({ signal }) => providersApi.listConnections({ signal }),
    enabled: open,
  });
  const { configuredEngines, unverifiedEngines } = useMemo(
    () => availableEngines(connectionsQuery.data),
    [connectionsQuery.data],
  );
  const [promptSetId, setPromptSetId] = useState<string | null>(null);
  const [engines, setEngines] = useState<LogicalEngine[]>([]);
  const [repetitions, setRepetitions] = useState(DEFAULT_REPETITIONS);
  const [connectOpen, setConnectOpen] = useState(false);
  const effectivePromptSetId =
    fixedPromptSetId ?? promptSetId ?? promptSetsQuery.data?.[0]?.id ?? null;
  const selection = {
    projectId,
    promptSetId: effectivePromptSetId,
    engines,
    repetitions,
    auditScope,
  };
  const ready = canLaunch(selection);
  const estimateQuery = useQuery({
    queryKey: ['audit-estimate', selection],
    queryFn: () => runsApi.estimateAudit(buildLaunchPayload(selection)),
    enabled: open && ready,
  });
  const reset = () => {
    setEngines([]);
    setPromptSetId(null);
    setRepetitions(DEFAULT_REPETITIONS);
  };
  const launchMutation = useMutation({
    mutationFn: () => runsApi.launchAudit(buildLaunchPayload(selection)),
    onSuccess: async (audit) => {
      queryClient.setQueryData(queryKeys.runs.detail(audit.id), audit);
      await queryClient.invalidateQueries({ queryKey: queryKeys.runs.all });
      onOpenChange(false);
      reset();
      onLaunched?.(audit);
    },
  });
  const launchNotice = launchMutation.isError
    ? mutationNoticeForError(launchMutation.error, { action: 'launch the audit' })
    : null;

  return (
    <LaunchDialogView
      open={open}
      onOpenChange={onOpenChange}
      promptSets={promptSetsQuery.data ?? []}
      promptSetsLoading={promptSetsQuery.isLoading}
      configuredEngines={configuredEngines}
      unverifiedEngines={unverifiedEngines}
      promptSetId={effectivePromptSetId}
      setPromptSetId={setPromptSetId}
      engines={engines}
      setEngines={setEngines}
      repetitions={repetitions}
      setRepetitions={setRepetitions}
      estimate={estimateQuery.data}
      launchPending={launchMutation.isPending}
      launchNotice={launchNotice}
      onLaunch={() => launchMutation.mutate()}
      connectOpen={connectOpen}
      setConnectOpen={setConnectOpen}
      promptSetLocked={Boolean(fixedPromptSetId)}
    />
  );
}
