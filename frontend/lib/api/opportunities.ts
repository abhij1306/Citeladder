/**
 * Opportunities domain endpoints + query/mutation options.
 *
 * Owns transport for the Opportunities slice: the priority-sorted keyset
 * catalog, the immutable recompute snapshots (summary + recompute), the row
 * detail, the one mutation (human workflow status), and same-origin export
 * URLs. Every JSON response passes through `strictValidate` (fail loud on any
 * drift — the backend is the source of truth). All paths are relative
 * `/api/v1` (same-origin proxy, invariant 12) and every read accepts an
 * `AbortSignal` via `ApiRequestOptions`.
 */
import { mutationOptions, queryOptions } from '@tanstack/react-query';

import { API_BASE_URL, apiClient, type ApiRequestOptions } from './client';
import { queryKeys } from './query-keys';
import {
  opportunitiesPageSchema,
  opportunityDetailSchema,
  opportunitySummarySchema,
  opportunitySchema,
  opportunityGuidanceHistorySchema,
  opportunityGuidanceItemSchema,
  opportunityOrderResponseSchema,
  recomputeResponseSchema,
  strictValidate,
} from './schemas';
import { definedQuery, withQuery } from './shared';
import type {
  OpportunitiesPage,
  Opportunity,
  OpportunityDetail,
  OpportunityStatus,
  OpportunitySummary,
  RecomputeResponse,
  OpportunityGuidanceHistory,
  OpportunityGuidanceItem,
} from './types';

/** Keyset catalog params. Ordering is server-owned (priority desc, id desc). */
export type OpportunitiesParams = {
  cursor?: string;
  limit?: number;
  type?: string;
  severity?: string;
  status?: string;
  rule_id?: string;
  min_priority?: number;
};

/** `PATCH /opportunities/{id}` body — status is the ONLY mutable field. */
export type OpportunityStatusPatch = { status: OpportunityStatus };
export type OpportunityOrderUpdate = {
  ordered_opportunity_ids: string[];
  expected_version: number;
};

/** Optional recompute scope; omit both for the latest dashboard sources. */
export type RecomputeScope = { audit_id?: string; site_crawl_id?: string };

export const opportunitiesApi = {
  list: async (projectId: string, params?: OpportunitiesParams, options?: ApiRequestOptions) => {
    const path = withQuery(`/projects/${projectId}/opportunities`, definedQuery(params));
    const res = await apiClient.get<OpportunitiesPage>(path, options);
    return strictValidate(opportunitiesPageSchema, res, 'opportunities.list');
  },
  get: async (opportunityId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<OpportunityDetail>(`/opportunities/${opportunityId}`, options);
    return strictValidate(opportunityDetailSchema, res, 'opportunities.get');
  },
  updateStatus: async (
    opportunityId: string,
    status: OpportunityStatus,
    options?: ApiRequestOptions,
  ) => {
    const res = await apiClient.patch<Opportunity>(
      `/opportunities/${opportunityId}`,
      { status },
      options,
    );
    return strictValidate(opportunitySchema, res, 'opportunities.updateStatus');
  },
  updateOrder: async (
    projectId: string,
    input: OpportunityOrderUpdate,
    options?: ApiRequestOptions,
  ) => {
    const res = await apiClient.put(`/projects/${projectId}/opportunities/order`, input, options);
    return strictValidate(opportunityOrderResponseSchema, res, 'opportunities.updateOrder');
  },
  recompute: async (projectId: string, scope?: RecomputeScope, options?: ApiRequestOptions) => {
    const res = await apiClient.post<RecomputeResponse>(
      `/projects/${projectId}/opportunities/recompute`,
      scope ?? {},
      options,
    );
    return strictValidate(recomputeResponseSchema, res, 'opportunities.recompute');
  },
  summary: async (projectId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<OpportunitySummary>(
      `/projects/${projectId}/opportunities/summary`,
      options,
    );
    return strictValidate(opportunitySummarySchema, res, 'opportunities.summary');
  },
  createGuidance: async (
    opportunityId: string,
    idempotencyKey: string,
    options?: ApiRequestOptions,
  ) => {
    const res = await apiClient.post<OpportunityGuidanceItem>(
      `/opportunities/${opportunityId}/guidance`,
      {},
      { ...options, idempotencyKey },
    );
    return strictValidate(opportunityGuidanceItemSchema, res, 'opportunities.createGuidance');
  },
  getLatestGuidance: async (opportunityId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<OpportunityGuidanceItem | null>(
      `/opportunities/${opportunityId}/guidance`,
      options,
    );
    return strictValidate(
      opportunityGuidanceItemSchema.nullable(),
      res,
      'opportunities.getLatestGuidance',
    );
  },
  getGuidanceHistory: async (opportunityId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<OpportunityGuidanceHistory>(
      `/opportunities/${opportunityId}/guidance/history`,
      options,
    );
    return strictValidate(
      opportunityGuidanceHistorySchema,
      res,
      'opportunities.getGuidanceHistory',
    );
  },
  /** Same-origin export URLs (browser navigation / download links). */
  exportUrl: (
    projectId: string,
    format: 'csv' | 'md',
    filters?: Omit<OpportunitiesParams, 'cursor' | 'limit'>,
  ) =>
    withQuery(
      `${API_BASE_URL}/projects/${projectId}/opportunities/export.${format}`,
      definedQuery(filters),
    ),
};

function extractProjectId(queryKey: readonly unknown[] | undefined): string | undefined {
  if (!queryKey || queryKey[0] !== 'opportunities') return undefined;
  if (queryKey[1] === 'list' || queryKey[1] === 'summary') {
    return typeof queryKey[2] === 'string' ? queryKey[2] : undefined;
  }
  return undefined;
}

function isSameProjectQuery(
  previousQuery: { queryKey: readonly unknown[] } | undefined,
  projectId: string,
): boolean {
  return extractProjectId(previousQuery?.queryKey) === projectId;
}

/**
 * React Query option factories. The query key ↔ endpoint pairing lives here
 * so screens pass these straight to `useQuery` / `useMutation`. Every
 * `queryFn` forwards the abort signal.
 */
export const opportunitiesQueries = {
  list: (projectId: string, params?: OpportunitiesParams) =>
    queryOptions({
      queryKey: queryKeys.opportunities.list(projectId, {
        cursor: params?.cursor ?? null,
        limit: params?.limit ?? null,
        type: params?.type ?? null,
        severity: params?.severity ?? null,
        status: params?.status ?? null,
        rule_id: params?.rule_id ?? null,
        min_priority: params?.min_priority ?? null,
      }),
      queryFn: ({ signal }) => opportunitiesApi.list(projectId, params, { signal }),
      placeholderData: (previousData, previousQuery) =>
        isSameProjectQuery(previousQuery, projectId) ? previousData : undefined,
    }),
  detail: (opportunityId: string) =>
    queryOptions({
      queryKey: queryKeys.opportunities.detail(opportunityId),
      queryFn: ({ signal }) => opportunitiesApi.get(opportunityId, { signal }),
    }),
  summary: (projectId: string) =>
    queryOptions({
      queryKey: queryKeys.opportunities.summary(projectId),
      queryFn: ({ signal }) => opportunitiesApi.summary(projectId, { signal }),
      placeholderData: (previousData, previousQuery) =>
        isSameProjectQuery(previousQuery, projectId) ? previousData : undefined,
    }),
  guidance: (opportunityId: string) =>
    queryOptions({
      queryKey: queryKeys.opportunities.guidance(opportunityId),
      queryFn: ({ signal }) => opportunitiesApi.getLatestGuidance(opportunityId, { signal }),
    }),
  guidanceHistory: (opportunityId: string) =>
    queryOptions({
      queryKey: queryKeys.opportunities.guidanceHistory(opportunityId),
      queryFn: ({ signal }) => opportunitiesApi.getGuidanceHistory(opportunityId, { signal }),
    }),
};

export const opportunitiesMutations = {
  updateStatus: () =>
    mutationOptions({
      mutationFn: (vars: { opportunityId: string; status: OpportunityStatus }) =>
        opportunitiesApi.updateStatus(vars.opportunityId, vars.status),
    }),
  recompute: () =>
    mutationOptions({
      mutationFn: (vars: { projectId: string; scope?: RecomputeScope }) =>
        opportunitiesApi.recompute(vars.projectId, vars.scope),
    }),
  createGuidance: () =>
    mutationOptions({
      mutationFn: (vars: { opportunityId: string; idempotencyKey: string }) =>
        opportunitiesApi.createGuidance(vars.opportunityId, vars.idempotencyKey),
    }),
};
