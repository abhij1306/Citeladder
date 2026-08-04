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
  contentGenerationDetailSchema,
  contentGenerationListItemSchema,
  strictValidate,
} from './schemas';
import { definedQuery, withQuery } from './shared';
import { z } from 'zod';
import type { ContentGenerationDetail, ContentGenerationListItem } from './types';
import { CONTENT_LIST_DEFAULT_LIMIT } from '@/lib/config/operational';

export {
  CONTENT_DETAIL_POLL_MS,
  CONTENT_LIST_DEFAULT_LIMIT,
  CONTENT_LIST_POLL_MS,
  CONTENT_PROMPT_MAX_LEN,
} from '@/lib/config/operational';

/** The only output type currently supported (backend `CONTENT_DEFAULT_OUTPUT_TYPE`). */
export const CONTENT_OUTPUT_TYPE_WEBSITE_PAGE = 'website_page';

const contentGenerationListSchema = z.array(contentGenerationListItemSchema);

/** `POST /content/generations` body. Workspace rides the session/header. */
export type EnqueueGenerationInput = {
  project_id: string;
  prompt: string;
  output_type?: string;
  skill_id?: 'youtube' | 'reddit' | 'blog' | 'article';
  opportunity_id?: string;
  website_context_enabled?: boolean;
};

export const contentApi = {
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
