/**
 * Client for the website-grounded Content generation queue.
 *
 * Content has one workflow: enqueue, inspect bounded history/detail, retry,
 * cancel, regenerate, and record feedback. Website evidence is mandatory and
 * is assembled by the backend from persisted Site Health artifacts.
 */
import { z } from 'zod';

import { CONTENT_LIST_DEFAULT_LIMIT } from '@/lib/config/operational';

import { apiClient, type ApiRequestOptions } from './client';
import {
  contentGenerationDetailSchema,
  contentGenerationListItemSchema,
  contentSkillSchema,
  strictValidate,
} from './schemas';
import { definedQuery, withQuery } from './shared';
import type { ContentGenerationDetail, ContentGenerationListItem } from './types';

export {
  CONTENT_DETAIL_POLL_MS,
  CONTENT_LIST_DEFAULT_LIMIT,
  CONTENT_LIST_POLL_MS,
  CONTENT_PROMPT_MAX_LEN,
} from '@/lib/config/operational';

export const CONTENT_OUTPUT_TYPE_WEBSITE_PAGE = 'website_page';
export type ContentSkill = z.infer<typeof contentSkillSchema>;

const contentGenerationListSchema = z.array(contentGenerationListItemSchema);

export type EnqueueGenerationInput = {
  project_id: string;
  prompt: string;
  output_type?: string;
  skill_id?: ContentSkill;
  opportunity_id?: string;
};

export const contentApi = {
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
    options?: ApiRequestOptions,
  ): Promise<ContentGenerationDetail> => {
    const response = await apiClient.post<ContentGenerationDetail>(
      `/content/generations/${generationId}/feedback`,
      { feedback },
      options,
    );
    return strictValidate(contentGenerationDetailSchema, response, 'content.recordFeedback');
  },
};
