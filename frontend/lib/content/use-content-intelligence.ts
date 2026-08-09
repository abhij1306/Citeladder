'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { contentApi, type ContentSkill } from '@/lib/api/content';
import { queryKeys } from '@/lib/api/query-keys';
import { newIdempotencyKey } from '@/lib/content/use-content-generations';

export function useContentIntelligence(projectId: string | null) {
  const queryClient = useQueryClient();
  const enabled = Boolean(projectId);
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.content.all });
  };

  const strategyQuery = useQuery({
    queryKey: queryKeys.content.strategy(projectId ?? ''),
    queryFn: ({ signal }) => contentApi.getStrategy(projectId ?? '', { signal }),
    enabled,
  });
  const inventoryQuery = useQuery({
    queryKey: queryKeys.content.inventory(projectId ?? ''),
    queryFn: ({ signal }) => contentApi.listInventory(projectId ?? '', { signal }),
    enabled,
  });
  const briefsQuery = useQuery({
    queryKey: queryKeys.content.briefs(projectId ?? ''),
    queryFn: ({ signal }) => contentApi.listBriefs(projectId ?? '', { signal }),
    enabled,
  });
  const revisionsQuery = useQuery({
    queryKey: queryKeys.content.revisions(projectId ?? ''),
    queryFn: ({ signal }) => contentApi.listRevisions(projectId ?? '', { signal }),
    enabled,
  });
  const verificationsQuery = useQuery({
    queryKey: queryKeys.content.verifications(projectId ?? ''),
    queryFn: ({ signal }) => contentApi.listVerifications(projectId ?? '', { signal }),
    enabled,
  });

  const recomputeMutation = useMutation({
    mutationFn: () => contentApi.recomputeStrategy(projectId ?? ''),
    onSuccess: invalidate,
  });
  const createBriefMutation = useMutation({
    mutationFn: (input: { questionId: string; targetUrl: string }) =>
      contentApi.createBrief({
        project_id: projectId ?? '',
        question_id: input.questionId,
        target_url: input.targetUrl,
      }),
    onSuccess: invalidate,
  });
  const generateBriefMutation = useMutation({
    mutationFn: (input: { briefId: string; skillId: ContentSkill }) =>
      contentApi.generateBrief(input.briefId, input.skillId, newIdempotencyKey()),
    onSuccess: invalidate,
  });
  const createRevisionMutation = useMutation({
    mutationFn: (generationId: string) => contentApi.createRevision(generationId),
    onSuccess: invalidate,
  });
  const updateRevisionMutation = useMutation({
    mutationFn: (input: { revisionId: string; visibleContent: string }) =>
      contentApi.updateRevision(input.revisionId, input.visibleContent, null),
    onSuccess: invalidate,
  });
  const transitionRevisionMutation = useMutation({
    mutationFn: (input: {
      revisionId: string;
      state: 'saved' | 'published_claimed' | 'discarded';
      targetUrl?: string;
    }) => contentApi.transitionRevision(input.revisionId, input.state, input.targetUrl),
    onSuccess: invalidate,
  });
  const verifyRevisionMutation = useMutation({
    mutationFn: (input: { revisionId: string; siteSnapshotId: string }) =>
      contentApi.verifyRevision(input.revisionId, input.siteSnapshotId),
    onSuccess: invalidate,
  });
  const exportRevisionMutation = useMutation({
    mutationFn: (revisionId: string) => contentApi.exportRevision(revisionId),
  });

  return {
    strategyQuery,
    inventoryQuery,
    briefsQuery,
    revisionsQuery,
    verificationsQuery,
    recomputeMutation,
    createBriefMutation,
    generateBriefMutation,
    createRevisionMutation,
    updateRevisionMutation,
    transitionRevisionMutation,
    verifyRevisionMutation,
    exportRevisionMutation,
  };
}
