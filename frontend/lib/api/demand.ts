/** Typed, strict client for persisted Demand Intelligence projections. */
import { z } from 'zod';

import { apiClient, type ApiRequestOptions } from './client';

const signalSchema = z
  .object({
    id: z.string().uuid(),
    snapshot_id: z.string().uuid(),
    signal_type: z.string(),
    state: z.string(),
    audience: z.string(),
    intent: z.string(),
    journey_stage: z.string(),
    topic_cluster: z.string(),
    page_url: z.string(),
    evidence: z.record(z.string(), z.unknown()),
    metrics: z.record(z.string(), z.unknown()),
    coverage: z.record(z.string(), z.unknown()),
    limitations: z.array(z.string()),
    priority_score: z.number().nullable(),
    priority_inputs: z.record(z.string(), z.unknown()),
    model_provenance: z.record(z.string(), z.unknown()).nullable(),
    created_at: z.string(),
  })
  .strict();

const snapshotSchema = z
  .object({
    id: z.string().uuid(),
    project_id: z.string().uuid(),
    window_start: z.string(),
    window_end: z.string(),
    source_hash: z.string(),
    site_snapshot_id: z.string().uuid().nullable(),
    prior_snapshot_id: z.string().uuid().nullable(),
    source_artifact_ids: z.array(z.string()),
    source_metric_row_ids: z.array(z.string()),
    source_audit_ids: z.array(z.string()),
    journey_version_ids: z.array(z.string()),
    coverage: z.record(z.string(), z.unknown()),
    summary: z.record(z.string(), z.unknown()),
    comparison: z.record(z.string(), z.unknown()).nullable(),
    formula_version: z.string(),
    analyzer_version: z.string(),
    created_at: z.string(),
    signals: z.array(signalSchema),
  })
  .strict();

const snapshotListSchema = z.object({ items: z.array(snapshotSchema) }).strict();
const capabilitySchema = z
  .object({
    provider: z.string(),
    dataset: z.string(),
    state: z.string(),
    latest_artifact_id: z.string().uuid().nullable(),
    coverage: z.record(z.string(), z.unknown()),
    provider_metadata: z.record(z.string(), z.unknown()),
  })
  .strict();
const capabilityListSchema = z.object({ datasets: z.array(capabilitySchema) }).strict();
export type DemandSnapshot = z.infer<typeof snapshotSchema>;

export const demandApi = {
  listSnapshots: async (projectId: string, options?: ApiRequestOptions) =>
    snapshotListSchema.parse(
      await apiClient.get<unknown>(`/projects/${projectId}/demand/snapshots?limit=20`, options),
    ),
  getSnapshot: async (projectId: string, snapshotId: string, options?: ApiRequestOptions) =>
    snapshotSchema.parse(
      await apiClient.get<unknown>(
        `/projects/${projectId}/demand/snapshots/${snapshotId}`,
        options,
      ),
    ),
  getCapabilities: async (projectId: string, options?: ApiRequestOptions) =>
    capabilityListSchema.parse(
      await apiClient.get<unknown>(`/projects/${projectId}/demand/capabilities`, options),
    ),
};
