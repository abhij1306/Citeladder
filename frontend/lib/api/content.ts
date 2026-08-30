/**
 * Client for the website-grounded Content generation queue.
 *
 * Content has one workflow: enqueue, inspect bounded history/detail, retry,
 * cancel, regenerate, and record feedback. Generation context (brand, task,
 * relevant crawl pages) is assembled by the backend; `getContextPreview`
 * reports what is available before a draft is requested.
 */
import { z } from 'zod';

import { CONTENT_LIST_DEFAULT_LIMIT } from '@/lib/config/operational';

import { apiClient, type ApiRequestOptions } from './client';
import {
  contentContextPreviewSchema,
  contentGenerationDetailSchema,
  contentGenerationListItemSchema,
  contentSkillCatalogSchema,
  contentSkillViewSchema,
  strictValidate,
} from './schemas';
import { definedQuery, withQuery } from './shared';
import type {
  ContentContextPreview,
  ContentFeedbackReason,
  ContentGenerationDetail,
  ContentGenerationListItem,
} from './types';

export {
  CONTENT_DETAIL_POLL_MS,
  CONTENT_LIST_DEFAULT_LIMIT,
  CONTENT_LIST_POLL_MS,
  CONTENT_PROMPT_MAX_LEN,
} from '@/lib/config/operational';

/** A skill id. The catalog is server-owned — never hardcode the set. */
type ContentSkill = string;
export type ContentSkillView = z.infer<typeof contentSkillViewSchema>;
export type ContentSkillCatalog = z.infer<typeof contentSkillCatalogSchema>;

const contentGenerationListSchema = z.array(contentGenerationListItemSchema);

export type SiteHealthReferenceInput = {
  project_id: string;
  crawl_id: string;
  site_url_id: string;
  source_analysis_id: string;
  dimension: string;
  checkpoint_ids: string[];
};

export type EnqueueGenerationInput = {
  project_id: string;
  prompt: string;
  output_type?: string;
  skill_id?: ContentSkill;
  opportunity_id?: string;
  site_health_reference?: SiteHealthReferenceInput;
};

export const contentApi = {
  /** The reusable output formats a generation may request. */
  listSkills: async (options?: ApiRequestOptions): Promise<ContentSkillCatalog> => {
    const response = await apiClient.get<unknown>('/content/skills', options);
    return strictValidate(contentSkillCatalogSchema, response, 'content.listSkills');
  },

  /** What would ground a draft for this project right now. */
  getContextPreview: async (
    projectId: string,
    options?: ApiRequestOptions,
  ): Promise<ContentContextPreview> => {
    const path = withQuery('/content/context-preview', definedQuery({ project_id: projectId }));
    const response = await apiClient.get<unknown>(path, options);
    return strictValidate(contentContextPreviewSchema, response, 'content.getContextPreview');
  },

  listGenerations: async (
    projectId: string,
    limit: number = CONTENT_LIST_DEFAULT_LIMIT,
    options?: ApiRequestOptions,
  ): Promise<ContentGenerationListItem[]> => {
    const path = withQuery('/content/generations', definedQuery({ project_id: projectId, limit }));
    const response = await apiClient.get<ContentGenerationListItem[]>(path, options);
    return strictValidate(contentGenerationListSchema, response, 'content.listGenerations');
  },

  enqueueGeneration: async (
    input: EnqueueGenerationInput,
    idempotencyKey?: string,
    options?: ApiRequestOptions,
  ): Promise<ContentGenerationDetail> => {
    const response = await apiClient.post<ContentGenerationDetail>('/content/generations', input, {
      ...options,
      idempotencyKey,
    });
    return strictValidate(contentGenerationDetailSchema, response, 'content.enqueueGeneration');
  },

  getGeneration: async (
    generationId: string,
    options?: ApiRequestOptions,
  ): Promise<ContentGenerationDetail> => {
    const response = await apiClient.get<ContentGenerationDetail>(
      `/content/generations/${generationId}`,
      options,
    );
    return strictValidate(contentGenerationDetailSchema, response, 'content.getGeneration');
  },

  regenerateGeneration: async (
    generationId: string,
    options?: ApiRequestOptions,
  ): Promise<ContentGenerationDetail> => {
    const response = await apiClient.post<ContentGenerationDetail>(
      `/content/generations/${generationId}/regenerate`,
      undefined,
      options,
    );
    return strictValidate(contentGenerationDetailSchema, response, 'content.regenerateGeneration');
  },

  tryAgainGeneration: async (
    generationId: string,
    options?: ApiRequestOptions,
  ): Promise<ContentGenerationDetail> => {
    const response = await apiClient.post<ContentGenerationDetail>(
      `/content/generations/${generationId}/try-again`,
      undefined,
      options,
    );
    return strictValidate(contentGenerationDetailSchema, response, 'content.tryAgainGeneration');
  },

  cancelGeneration: async (
    generationId: string,
    options?: ApiRequestOptions,
  ): Promise<ContentGenerationDetail> => {
    const response = await apiClient.post<ContentGenerationDetail>(
      `/content/generations/${generationId}/cancel`,
      undefined,
      options,
    );
    return strictValidate(contentGenerationDetailSchema, response, 'content.cancelGeneration');
  },

  recordFeedback: async (
    generationId: string,
    feedback: 'accepted' | 'rejected',
    reason?: ContentFeedbackReason,
    options?: ApiRequestOptions,
  ): Promise<ContentGenerationDetail> => {
    const response = await apiClient.post<ContentGenerationDetail>(
      `/content/generations/${generationId}/feedback`,
      reason ? { feedback, reason } : { feedback },
      options,
    );
    return strictValidate(contentGenerationDetailSchema, response, 'content.recordFeedback');
  },
};
