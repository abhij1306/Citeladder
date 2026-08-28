'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import { mutationNoticeForError } from '@/lib/api/mutation-notice';
import { promptsApi } from '@/lib/api/prompts';
import { providersApi } from '@/lib/api/providers';
import { queryKeys } from '@/lib/api/query-keys';
import { runsApi } from '@/lib/api/runs';
import type { Audit, LogicalEngine, PromptSet } from '@/lib/api/types';
import { ENGINE_ORDER, isConfigured, isVerified } from '@/lib/providers/catalog';
import {
  auditablePrompts,
  buildLaunchPayload,
  canLaunch,
  DEFAULT_REPETITIONS,
  promptBatches,
} from '@/lib/runs/launch';

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

function fixedPromptSelection(
  fixedPromptSetId: string | undefined,
  fixedPromptIds: string[] | undefined,
  promptSelectionLabel: string | undefined,
) {
  const count = fixedPromptIds?.length ?? 0;
  return {
    locked: count > 0 || Boolean(fixedPromptSetId),
    label:
      promptSelectionLabel ??
      (count ? `${count} selected ${count === 1 ? 'prompt' : 'prompts'}` : undefined),
  };
}

function batchSelection(
  promptSets: PromptSet[] | undefined,
  selectedPromptSetId: string | null,
  fixedPromptSetId: string | undefined,
  fixedPromptIds: string[] | undefined,
  batchIndex: number | null,
  locked: boolean,
) {
  const effectivePromptSetId =
    fixedPromptSetId ?? selectedPromptSetId ?? promptSets?.[0]?.id ?? null;
  const set = promptSets?.find((item) => item.id === effectivePromptSetId);
  const batches = locked ? [] : promptBatches(auditablePrompts(set));
  const selectedBatch = batchIndex === null ? undefined : batches[batchIndex];
  const selectedBatchMissing = batchIndex !== null && selectedBatch === undefined;
  return {
    effectivePromptSetId,
    batches,
    payloadPromptSetId: selectedBatchMissing ? null : effectivePromptSetId,
    promptIds: fixedPromptIds ?? selectedBatch?.map((prompt) => prompt.id),
  };
}

/** Launch controller: queries, mutations, and form selection stay here; UI is in the view. */
export function LaunchDialog({
  open,
  onOpenChange,
  projectId,
  onLaunched,
  fixedPromptSetId,
  fixedPromptIds,
  promptSelectionLabel,
  auditScope = 'brand',
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  onLaunched?: (audit: Audit) => void;
  fixedPromptSetId?: string;
  fixedPromptIds?: string[];
  promptSelectionLabel?: string;
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
  // One contract, derived from the same values the payload is built from:
  // `fixedPromptIds` wins in `buildLaunchPayload`, so it must also lock the
  // field and name the selection. Locking only on `fixedPromptSetId` left the
  // commerce caller showing an editable prompt-set select whose value the
  // payload ignored.
  const fixedSelection = fixedPromptSelection(
    fixedPromptSetId,
    fixedPromptIds,
    promptSelectionLabel,
  );
  const [promptSetId, setPromptSetId] = useState<string | null>(null);
  const [engines, setEngines] = useState<LogicalEngine[]>([]);
  const [repetitions, setRepetitions] = useState(DEFAULT_REPETITIONS);
  const [connectOpen, setConnectOpen] = useState(false);
  // `null` means the whole set. A caller that already fixed the prompts owns
  // the selection outright, so batching is not offered there.
  const [batchIndex, setBatchIndex] = useState<number | null>(null);
  const promptSelection = useMemo(
    () =>
      batchSelection(
        promptSetsQuery.data,
        promptSetId,
        fixedPromptSetId,
        fixedPromptIds,
        batchIndex,
        fixedSelection.locked,
      ),
    [
      promptSetsQuery.data,
      promptSetId,
      fixedPromptSetId,
      fixedPromptIds,
      batchIndex,
      fixedSelection.locked,
    ],
  );
  const selection = {
    projectId,
    promptSetId: promptSelection.payloadPromptSetId,
    promptIds: promptSelection.promptIds,
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
    setBatchIndex(null);
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
      promptSetId={promptSelection.effectivePromptSetId}
      setPromptSetId={(id) => {
        // A batch index means nothing against a different set's prompts.
        setPromptSetId(id);
        setBatchIndex(null);
      }}
      batches={promptSelection.batches}
      batchIndex={batchIndex}
      setBatchIndex={setBatchIndex}
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
      promptSetLocked={fixedSelection.locked}
      promptSelectionLabel={fixedSelection.label}
      selectionReady={ready}
    />
  );
}
