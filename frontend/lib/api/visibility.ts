/**
 * Visibility domain endpoint (F2): the selected-run dashboard projection —
 * Visibility Score, per-engine comparison, and the brand-vs-competitor rankings
 * table. `sentiment` / `avg_position` are present but nullable. Defaults
 * to the project's latest completed audit when `audit_id` is omitted. Response
 * passes through `strictValidate`.
 *
 * `getVisibilityTrends` is the additive cross-run trend projection
 * (`/projects/{id}/visibility/trends`): an ordered series of
 * `VisibilityTrendPoint`s over persisted `MetricSnapshot` rows, filtered by
 * engine/date and bucketed by run/week/month. Same-origin `/api/v1` only.
 */
import { z } from 'zod';

import { apiClient, type ApiRequestOptions } from './client';
import {
  competitorSchema,
  observedCompetitorSchema,
  promptMetricItemSchema,
  strictValidate,
  visibilityEvidenceResponseSchema,
  visibilitySchema,
  visibilityTrendListSchema,
} from './schemas';
import { definedQuery, withQuery } from './shared';
import type {
  ObservedCompetitor,
  Competitor,
  PromptMetricItem,
  Visibility,
  VisibilityEvidenceResponse,
  VisibilityTrendPoint,
} from './types';

const promptMetricListSchema = z.array(promptMetricItemSchema);
const observedCompetitorListSchema = z.array(observedCompetitorSchema);

/** Filters for the cross-run trend request (all optional; same-origin only). */
type VisibilityTrendParams = {
  cohort?: 'core' | 'comparison';
  /** Logical engine slice (`chatgpt` | `gemini` | `claude`); omit for all. */
  engine?: string;
  /** Inclusive UTC lower bound (ISO 8601) for the completion window. */
  from?: string;
  /** Inclusive UTC upper bound (ISO 8601) for the completion window. */
  to?: string;
  /** Bucketing: `run` (default) | `week` | `month`. */
  granularity?: string;
};

/**
 * Filters for the shared execution-evidence request (all optional). When both
 * `audit_id` and a date bound are set the backend intersects them (the selected
 * audit must fall inside the inclusive window). Same-origin only.
 */
type VisibilityEvidenceParams = {
  cohort?: 'core' | 'comparison';
  /** Restrict to one audit in the authorized project. */
  audit_id?: string;
  /** Restrict by the source prompt frozen on `AuditPromptSnapshot.prompt_id`. */
  prompt_id?: string;
  /** Logical engine slice (`chatgpt` | `gemini` | `claude`); omit for all. */
  engine?: string;
  /** Inclusive UTC lower bound (ISO 8601) for the completion window. */
  from?: string;
  /** Inclusive UTC upper bound (ISO 8601) for the completion window. */
  to?: string;
  /** Newest-window size (default 100, max 500). */
  limit?: number;
};

export const visibilityApi = {
  getProjectVisibility: async (
    projectId: string,
    params?: { audit_id?: string; cohort?: 'core' | 'comparison' },
    options?: ApiRequestOptions,
  ) => {
    const path = withQuery(`/projects/${projectId}/visibility`, definedQuery(params));
    const res = await apiClient.get<Visibility>(path, options);
    return strictValidate(visibilitySchema, res, 'visibility.getProjectVisibility');
  },

  /**
   * Cross-run Visibility trend projection for a project (roadmap surface, now
   * live). An ordered series of `VisibilityTrendPoint`s over the project's
   * persisted dashboard-ready `MetricSnapshot` rows — optionally filtered by
   * `engine` and an inclusive UTC `from`/`to` window, and bucketed by
   * `granularity`. Same-origin relative path only; response is strictly
   * validated (backend is the source of truth).
   */
  getVisibilityTrends: async (
    projectId: string,
    params?: VisibilityTrendParams,
    options?: ApiRequestOptions,
  ): Promise<VisibilityTrendPoint[]> => {
    const path = withQuery(`/projects/${projectId}/visibility/trends`, definedQuery(params));
    const res = await apiClient.get<VisibilityTrendPoint[]>(path, options);
    return strictValidate(visibilityTrendListSchema, res, 'visibility.getVisibilityTrends');
  },

  /**
   * Shared persisted execution-evidence dataset for the Mentions & Citations
   * and Query Fanout tabs (`/projects/{id}/visibility/evidence`). Returns a
   * bounded newest-first window of `VisibilityExecutionEvidence` plus a
   * `truncated` flag — no provider is called and no evidence is inferred at read
   * time. Same-origin relative path only; response is strictly validated.
   */
  getVisibilityEvidence: async (
    projectId: string,
    params?: VisibilityEvidenceParams,
    options?: ApiRequestOptions,
  ): Promise<VisibilityEvidenceResponse> => {
    const path = withQuery(`/projects/${projectId}/visibility/evidence`, definedQuery(params));
    const res = await apiClient.get<VisibilityEvidenceResponse>(path, options);
    return strictValidate(
      visibilityEvidenceResponseSchema,
      res,
      'visibility.getVisibilityEvidence',
    );
  },
  getPromptMetrics: async (
    projectId: string,
    auditId?: string,
    options?: ApiRequestOptions,
  ): Promise<PromptMetricItem[]> => {
    const path = withQuery(
      `/projects/${projectId}/visibility/prompts`,
      definedQuery({ audit_id: auditId }),
    );
    const res = await apiClient.get<PromptMetricItem[]>(path, options);
    return strictValidate(promptMetricListSchema, res, 'visibility.getPromptMetrics');
  },
  listCompetitorSuggestions: async (
    projectId: string,
    options?: ApiRequestOptions,
  ): Promise<ObservedCompetitor[]> => {
    const res = await apiClient.get<ObservedCompetitor[]>(
      `/projects/${projectId}/competitor-suggestions`,
      options,
    );
    return strictValidate(
      observedCompetitorListSchema,
      res,
      'visibility.listCompetitorSuggestions',
    );
  },
  acceptCompetitorSuggestion: async (
    projectId: string,
    candidateId: string,
    options?: ApiRequestOptions,
  ): Promise<Competitor> => {
    const res = await apiClient.post<Competitor>(
      `/projects/${projectId}/competitor-suggestions/${candidateId}/accept`,
      undefined,
      options,
    );
    return strictValidate(competitorSchema, res, 'visibility.acceptCompetitorSuggestion');
  },
};
