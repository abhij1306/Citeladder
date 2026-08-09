/**
 * Content-generation domain endpoints + client-side constants (F2).
 *
 * Owns transport for the Content slice: enqueue (with an optional
 * `Idempotency-Key`), bounded history list, detail, regenerate, try-again,
 * and cancel. Every JSON response passes through `strictValidate` (fail loud
 * on any drift). All paths are relative `/api/v1` (same-origin proxy,
 * invariant 12); the provider API key never appears on the wire (invariant 6).
 *
 * This module is the single owner of the content client constants (prompt
 * cap, output type, list limit, poll cadences) — invariant 1, one owner.
 */
import { apiClient, type ApiRequestOptions } from './client';
import {
  contentBriefSchema,
  contentGenerationDetailSchema,
  contentGenerationListItemSchema,
  contentInventoryItemSchema,
  contentRevisionSchema,
  contentSkillSchema,
  contentStrategySchema,
  contentValidationSchema,
  contentVerificationSchema,
  strictValidate,
  taskContextPackageSchema,
} from './schemas';
import { definedQuery, withQuery } from './shared';
import { z } from 'zod';
import type {
  ContentBrief,
  ContentGenerationDetail,
  ContentGenerationListItem,
  ContentInventoryItem,
  ContentRevision,
  ContentStrategy,
  ContentValidation,
  ContentVerification,
  TaskContextPackage,
} from './types';
import { CONTENT_LIST_DEFAULT_LIMIT } from '@/lib/config/operational';

export {
  CONTENT_DETAIL_POLL_MS,
  CONTENT_LIST_DEFAULT_LIMIT,
  CONTENT_LIST_POLL_MS,
  CONTENT_PROMPT_MAX_LEN,
} from '@/lib/config/operational';

/** The only output type currently supported (backend `CONTENT_DEFAULT_OUTPUT_TYPE`). */
export const CONTENT_OUTPUT_TYPE_WEBSITE_PAGE = 'website_page';
export const CONTENT_INVENTORY_LIST_LIMIT = 250;
export type ContentSkill = z.infer<typeof contentSkillSchema>;

const contentGenerationListSchema = z.array(contentGenerationListItemSchema);
const contentInventoryListSchema = z.array(contentInventoryItemSchema);
const contentBriefListSchema = z.array(contentBriefSchema);
const contentRevisionListSchema = z.array(contentRevisionSchema);
const contentVerificationListSchema = z.array(contentVerificationSchema);

/** `POST /content/generations` body. Workspace rides the session/header. */
export type EnqueueGenerationInput = {
  project_id: string;
  prompt: string;
  output_type?: string;
  skill_id?: z.infer<typeof contentSkillSchema>;
  opportunity_id?: string;
  brief_id?: string;
  website_context_enabled?: boolean;
};

export const contentApi = {
  getStrategy: async (
    projectId: string,
    options?: ApiRequestOptions,
  ): Promise<ContentStrategy | null> => {
    const res = await apiClient.get<ContentStrategy | null>(
      withQuery('/content/strategy', definedQuery({ project_id: projectId })),
      options,
    );
    return strictValidate(contentStrategySchema.nullable(), res, 'content.getStrategy');
  },
  recomputeStrategy: async (
    projectId: string,
    options?: ApiRequestOptions,
  ): Promise<ContentStrategy> => {
    const res = await apiClient.post<ContentStrategy>(
      withQuery('/content/strategy/recompute', definedQuery({ project_id: projectId })),
      undefined,
      options,
    );
    return strictValidate(contentStrategySchema, res, 'content.recomputeStrategy');
  },
  listInventory: async (
    projectId: string,
    options?: ApiRequestOptions,
  ): Promise<ContentInventoryItem[]> => {
    const res = await apiClient.get<ContentInventoryItem[]>(
      withQuery(
        '/content/inventory',
        definedQuery({ project_id: projectId, limit: CONTENT_INVENTORY_LIST_LIMIT }),
      ),
      options,
    );
    return strictValidate(contentInventoryListSchema, res, 'content.listInventory');
  },
  listBriefs: async (projectId: string, options?: ApiRequestOptions): Promise<ContentBrief[]> => {
    const res = await apiClient.get<ContentBrief[]>(
      withQuery('/content/briefs', definedQuery({ project_id: projectId })),
      options,
    );
    return strictValidate(contentBriefListSchema, res, 'content.listBriefs');
  },
  createBrief: async (
    input: {
      project_id: string;
      question_id: string;
      kind?: string;
      target_url?: string;
      title?: string;
    },
    options?: ApiRequestOptions,
  ): Promise<ContentBrief> => {
    const res = await apiClient.post<ContentBrief>('/content/briefs', input, options);
    return strictValidate(contentBriefSchema, res, 'content.createBrief');
  },
  buildContext: async (
    briefId: string,
    options?: ApiRequestOptions,
  ): Promise<TaskContextPackage> => {
    const res = await apiClient.post<TaskContextPackage>(
      `/content/briefs/${briefId}/context`,
      undefined,
      options,
    );
    return strictValidate(taskContextPackageSchema, res, 'content.buildContext');
  },
  generateBrief: async (
    briefId: string,
    skillId: ContentSkill,
    idempotencyKey?: string,
    options?: ApiRequestOptions,
  ): Promise<ContentGenerationDetail> => {
    const res = await apiClient.post<ContentGenerationDetail>(
      `/content/briefs/${briefId}/generate`,
      { skill_id: skillId },
      { ...options, idempotencyKey },
    );
    return strictValidate(contentGenerationDetailSchema, res, 'content.generateBrief');
  },
  getValidation: async (
    generationId: string,
    options?: ApiRequestOptions,
  ): Promise<ContentValidation> => {
    const res = await apiClient.get<ContentValidation>(
      `/content/generations/${generationId}/validation`,
      options,
    );
    return strictValidate(contentValidationSchema, res, 'content.getValidation');
  },
  createRevision: async (
    generationId: string,
    visibleContent?: string,
    options?: ApiRequestOptions,
  ): Promise<ContentRevision> => {
    const res = await apiClient.post<ContentRevision>(
      `/content/generations/${generationId}/revision`,
      { visible_content: visibleContent ?? null, structured_data: null },
      options,
    );
    return strictValidate(contentRevisionSchema, res, 'content.createRevision');
  },
  listRevisions: async (
    projectId: string,
    options?: ApiRequestOptions,
  ): Promise<ContentRevision[]> => {
    const res = await apiClient.get<ContentRevision[]>(
      withQuery('/content/revisions', definedQuery({ project_id: projectId })),
      options,
    );
    return strictValidate(contentRevisionListSchema, res, 'content.listRevisions');
  },
  exportRevision: (revisionId: string, options?: ApiRequestOptions): Promise<Blob> =>
    apiClient.getBlob(`/content/revisions/${revisionId}/export`, options),
  updateRevision: async (
    revisionId: string,
    visibleContent: string,
    structuredData: Record<string, unknown> | null,
    options?: ApiRequestOptions,
  ): Promise<ContentRevision> => {
    const res = await apiClient.put<ContentRevision>(
      `/content/revisions/${revisionId}`,
      { visible_content: visibleContent, structured_data: structuredData },
      options,
    );
    return strictValidate(contentRevisionSchema, res, 'content.updateRevision');
  },
  transitionRevision: async (
    revisionId: string,
    state: 'saved' | 'published_claimed' | 'discarded',
    targetUrl = '',
    options?: ApiRequestOptions,
  ): Promise<ContentRevision> => {
    const res = await apiClient.post<ContentRevision>(
      `/content/revisions/${revisionId}/transition`,
      { state, target_url: targetUrl, reason: '' },
      options,
    );
    return strictValidate(contentRevisionSchema, res, 'content.transitionRevision');
  },
  listVerifications: async (
    projectId: string,
    options?: ApiRequestOptions,
  ): Promise<ContentVerification[]> => {
    const res = await apiClient.get<ContentVerification[]>(
      withQuery('/content/verifications', definedQuery({ project_id: projectId })),
      options,
    );
    return strictValidate(contentVerificationListSchema, res, 'content.listVerifications');
  },
  verifyRevision: async (
    revisionId: string,
    siteSnapshotId: string,
    options?: ApiRequestOptions,
  ): Promise<ContentVerification> => {
    const res = await apiClient.post<ContentVerification>(
      `/content/revisions/${revisionId}/verifications`,
      { site_snapshot_id: siteSnapshotId },
      options,
    );
    return strictValidate(contentVerificationSchema, res, 'content.verifyRevision');
  },
  listGenerations: async (
    projectId: string,
    limit: number = CONTENT_LIST_DEFAULT_LIMIT,
    options?: ApiRequestOptions,
  ): Promise<ContentGenerationListItem[]> => {
    const path = withQuery('/content/generations', definedQuery({ project_id: projectId, limit }));
    const res = await apiClient.get<ContentGenerationListItem[]>(path, options);
    return strictValidate(contentGenerationListSchema, res, 'content.listGenerations');
  },
  enqueueGeneration: async (
    input: EnqueueGenerationInput,
    idempotencyKey?: string,
    options?: ApiRequestOptions,
  ): Promise<ContentGenerationDetail> => {
    const res = await apiClient.post<ContentGenerationDetail>('/content/generations', input, {
      ...options,
      idempotencyKey,
    });
    return strictValidate(contentGenerationDetailSchema, res, 'content.enqueueGeneration');
  },
  getGeneration: async (
    generationId: string,
    options?: ApiRequestOptions,
  ): Promise<ContentGenerationDetail> => {
    const res = await apiClient.get<ContentGenerationDetail>(
      `/content/generations/${generationId}`,
      options,
    );
    return strictValidate(contentGenerationDetailSchema, res, 'content.getGeneration');
  },
  regenerateGeneration: async (
    generationId: string,
    options?: ApiRequestOptions,
  ): Promise<ContentGenerationDetail> => {
    const res = await apiClient.post<ContentGenerationDetail>(
      `/content/generations/${generationId}/regenerate`,
      undefined,
      options,
    );
    return strictValidate(contentGenerationDetailSchema, res, 'content.regenerateGeneration');
  },
  tryAgainGeneration: async (
    generationId: string,
    options?: ApiRequestOptions,
  ): Promise<ContentGenerationDetail> => {
    const res = await apiClient.post<ContentGenerationDetail>(
      `/content/generations/${generationId}/try-again`,
      undefined,
      options,
    );
    return strictValidate(contentGenerationDetailSchema, res, 'content.tryAgainGeneration');
  },
  cancelGeneration: async (
    generationId: string,
    options?: ApiRequestOptions,
  ): Promise<ContentGenerationDetail> => {
    const res = await apiClient.post<ContentGenerationDetail>(
      `/content/generations/${generationId}/cancel`,
      undefined,
      options,
    );
    return strictValidate(contentGenerationDetailSchema, res, 'content.cancelGeneration');
  },
  recordFeedback: async (
    generationId: string,
    feedback: 'accepted' | 'rejected',
    options?: ApiRequestOptions,
  ): Promise<ContentGenerationDetail> => {
    const res = await apiClient.post<ContentGenerationDetail>(
      `/content/generations/${generationId}/feedback`,
      { feedback },
      options,
    );
    return strictValidate(contentGenerationDetailSchema, res, 'content.recordFeedback');
  },
};
