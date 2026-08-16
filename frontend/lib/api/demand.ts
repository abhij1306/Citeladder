/** Typed, strict client for persisted Demand Intelligence projections. */
import { z } from 'zod';

import { apiClient, type ApiRequestOptions } from './client';

const signalSchema = z.strictObject({
  id: z.uuid(),
  snapshot_id: z.uuid(),
  signal_type: z.string(),
  state: z.string(),
  topic_cluster: z.string(),
  page_url: z.string(),
  evidence: z.record(z.string(), z.unknown()),
  metrics: z.record(z.string(), z.unknown()),
  coverage: z.record(z.string(), z.unknown()),
  limitations: z.array(z.string()),
  priority_score: z.number().nullable(),
  priority_inputs: z.record(z.string(), z.unknown()),
  created_at: z.string(),
});

const snapshotSchema = z.strictObject({
  id: z.uuid(),
  project_id: z.uuid(),
  window_start: z.string(),
  window_end: z.string(),
  source_hash: z.string(),
  prior_snapshot_id: z.uuid().nullable(),
  source_artifact_ids: z.array(z.string()),
  source_metric_row_ids: z.array(z.string()),
  coverage: z.record(z.string(), z.unknown()),
  summary: z.record(z.string(), z.unknown()),
  comparison: z.record(z.string(), z.unknown()).nullable(),
  formula_version: z.string(),
  analyzer_version: z.string(),
  created_at: z.string(),
  signals: z.array(signalSchema),
});

export type DemandSignal = z.infer<typeof signalSchema>;
export type DemandSnapshot = z.infer<typeof snapshotSchema>;

const recomputeResponseSchema = z.strictObject({
  task_id: z.uuid().nullable(),
  status: z.string(),
});

export type DemandRecomputeResponse = z.infer<typeof recomputeResponseSchema>;

export const demandApi = {
  getLatest: async (projectId: string, options?: ApiRequestOptions) =>
    snapshotSchema.parse(
      await apiClient.get<unknown>(`/projects/${projectId}/demand/latest`, options),
    ),
  recompute: async (
    projectId: string,
    payload: { window_start: string; window_end: string },
    options?: ApiRequestOptions,
  ) =>
    recomputeResponseSchema.parse(
      await apiClient.post<unknown>(`/projects/${projectId}/demand/recompute`, payload, options),
    ),
};
