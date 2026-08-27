'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { commerceApi } from '@/lib/api/commerce';
import { queryKeys } from '@/lib/api/query-keys';
import type { CommerceTarget, CompetitorDiscoveryTask } from '@/lib/api/schemas/commerce-suite';
import { ACTIVE_RUN_POLL_MS } from '@/lib/config/operational';

type Tasks = readonly CompetitorDiscoveryTask[];

/**
 * How often to re-read discovery tasks, or `false` once none are running.
 *
 * Pure and exported so the rule is testable without mounting the panel.
 */
export function discoveryPollInterval(tasks: Tasks | undefined): number | false {
  return (tasks ?? []).some((task) => !task.terminal) ? ACTIVE_RUN_POLL_MS : false;
}

/**
 * True when this read is the moment discovery stopped running.
 *
 * The panel used to refresh the candidates whenever the server's in-flight
 * list was empty, which missed the transition in both directions. A discovery
 * that terminalized between two polls never made that list non-empty, so the
 * count stayed at zero and the finished candidates were never fetched; and a
 * page reload dropped the launched ids, so nothing was watching them at all.
 *
 * Tracked ids keep being returned after they settle, so the terminal read is
 * `next` holding only terminal rows. The reload path has no tracked ids, so it
 * is the running-to-empty transition instead. Either way the candidate list is
 * refreshed exactly once, whether the run succeeded, failed, or was cancelled.
 */
export function discoverySettled(previous: Tasks | undefined, next: Tasks): boolean {
  const stillRunning = next.some((task) => !task.terminal);
  const wasRunning = (previous ?? []).some((task) => !task.terminal);
  return !stillRunning && (next.length > 0 || wasRunning);
}

/** Track competitor discovery for one project, from launch to terminal state. */
export function useCompetitorDiscovery(projectId: string) {
  const client = useQueryClient();
  // The ids the launch returned. They do not survive a reload, so an empty set
  // falls back to asking the server what is still in flight — the only form
  // reload recovery can take.
  const [trackedIds, setTrackedIds] = useState<string[]>([]);
  const queryKey = trackedIds.length
    ? queryKeys.commerce.discoveryTasks(projectId, trackedIds)
    : queryKeys.commerce.activeDiscoveries(projectId);
  const query = useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      const previous = client.getQueryData<CompetitorDiscoveryTask[]>(queryKey);
      const next = await commerceApi.competitorDiscoveries(
        projectId,
        trackedIds.length ? trackedIds : undefined,
        { signal },
      );
      if (discoverySettled(previous, next)) {
        void client.invalidateQueries({ queryKey: queryKeys.commerce.competitors(projectId) });
      }
      return next;
    },
    refetchInterval: (result) => discoveryPollInterval(result.state.data),
  });
  const discover = useMutation({
    mutationFn: (targets: CommerceTarget[]) => commerceApi.discoverCompetitors(projectId, targets),
    onSuccess: (data) => setTrackedIds(data.task_ids),
  });

  return { tasks: query.data ?? [], discover };
}
