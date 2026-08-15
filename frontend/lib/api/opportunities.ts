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
  implementationEventSchema,
  implementationEventsPageSchema,
  opportunitiesPageSchema,
  opportunityDetailSchema,
  opportunitySummarySchema,
  opportunitySchema,
  opportunityOrderResponseSchema,
  recomputeResponseSchema,
  strictValidate,
} from './schemas';
import { definedQuery, withQuery } from './shared';
import type {
  ImplementationEvent,
  OpportunitiesPage,
  Opportunity,
  OpportunityDetail,
  OpportunityStatus,
  OpportunitySummary,
  RecomputeResponse,
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
export type ExpectedCheck =
  | {
      kind: 'site_rule';
      target_site_url_id?: string;
      rule_id: string;
      expected_outcome: 'pass' | 'fail';
    }
  | {
      kind: 'page_fact';
      target_site_url_id?: string;
      fact_key: string;
      expected_value: unknown;
    }
  | {
      kind: 'visibility_metric' | 'traffic_metric';
      metric: string;
      direction: 'increase' | 'decrease' | 'equal';
      expected_value?: number;
      tolerance?: number;
    };
export type ImplementationEventCreate = {
  opportunity_id: string;
  target_site_url_ids: string[];
  generation_id?: string;
  declared_implemented_at: string;
  expected_checks: ExpectedCheck[];
};

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
  createImplementationEvent: async (
    projectId: string,
    input: ImplementationEventCreate,
    idempotencyKey: string,
    options?: ApiRequestOptions,
  ) => {
    const res = await apiClient.post<ImplementationEvent>(
      `/projects/${projectId}/opportunities/implementation-events`,
      input,
      { ...options, idempotencyKey, retryNetworkFailures: true },
    );
    return strictValidate(implementationEventSchema, res, 'opportunities.implementation.create');
  },
  listImplementationEvents: async (projectId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get(
      `/projects/${projectId}/opportunities/implementation-events`,
      options,
    );
    return strictValidate(
      implementationEventsPageSchema,
      res,
      'opportunities.implementation.list',
    );
  },
  getImplementationEvent: async (
    projectId: string,
    eventId: string,
    options?: ApiRequestOptions,
  ) => {
    const res = await apiClient.get(
      `/projects/${projectId}/opportunities/implementation-events/${eventId}`,
      options,
    );
    return strictValidate(implementationEventSchema, res, 'opportunities.implementation.get');
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
  implementationEvents: (projectId: string) =>
    queryOptions({
      queryKey: queryKeys.opportunities.implementationEvents(projectId),
      queryFn: ({ signal }) =>
        opportunitiesApi.listImplementationEvents(projectId, { signal }),
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
  createImplementationEvent: () =>
    mutationOptions({
      mutationFn: (vars: {
        projectId: string;
        input: ImplementationEventCreate;
        idempotencyKey: string;
      }) =>
        opportunitiesApi.createImplementationEvent(
          vars.projectId,
          vars.input,
          vars.idempotencyKey,
        ),
    }),
};
