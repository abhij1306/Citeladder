/** Strict client for the two bounded, read-only Growth Agent tasks. */
import { z } from 'zod';

import { apiClient, type ApiRequestOptions } from './client';

const agentTaskTypeSchema = z.enum(['explain', 'build_roadmap']);

const artifactReferenceSchema = z.object({
  kind: z.string(),
  id: z.uuid(),
});

const roadmapItemSchema = z.object({
  rank: z.number().int(),
  title: z.string(),
  remediation: z.string(),
  target_url: z.string().nullable(),
  priority_score: z.number(),
  severity: z.string(),
});

const evidenceSourceSchema = z.object({
  key: z.enum(['site_health', 'search_demand', 'opportunities', 'ai_visibility']),
  label: z.string(),
  availability: z.enum(['available', 'unavailable']),
  window: z.record(z.string(), z.string()).nullable(),
  coverage: z.record(z.string(), z.union([z.number(), z.string(), z.null()])).nullable(),
  reason: z.string().nullable(),
});

const agentResultSchema = z.object({
  summary: z.string(),
  observations: z.array(z.string()),
  roadmap_items: z.array(roadmapItemSchema),
  sources: z.array(evidenceSourceSchema),
  limitations: z.array(z.string()),
  artifact_refs: z.array(artifactReferenceSchema),
});

const agentTaskRunSummarySchema = z.object({
  id: z.uuid(),
  project_id: z.uuid(),
  task_type: agentTaskTypeSchema,
  objective: z.string(),
  status: z.string(),
  error_code: z.string(),
  error_detail: z.string(),
  attempt_count: z.number().int(),
  completed_at: z.string().nullable(),
  cancelled_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const agentTaskRunSchema = agentTaskRunSummarySchema.extend({
  result: agentResultSchema.nullable(),
});

export type AgentTaskType = z.infer<typeof agentTaskTypeSchema>;
export type AgentTaskRunSummary = z.infer<typeof agentTaskRunSummarySchema>;
export type AgentTaskRun = z.infer<typeof agentTaskRunSchema>;

export type AgentTaskInput = {
  project_id: string;
  task_type: AgentTaskType;
  objective: string;
};

export const agentApi = {
  listTasks: async (projectId: string, options?: ApiRequestOptions) =>
    z
      .array(agentTaskRunSummarySchema)
      .parse(
        await apiClient.get<unknown>(
          `/agent/tasks?project_id=${encodeURIComponent(projectId)}`,
          options,
        ),
      ),
  getTask: async (projectId: string, runId: string, options?: ApiRequestOptions) =>
    agentTaskRunSchema.parse(
      await apiClient.get<unknown>(
        `/agent/tasks/${encodeURIComponent(runId)}?project_id=${encodeURIComponent(projectId)}`,
        options,
      ),
    ),
  submitTask: async (input: AgentTaskInput, idempotencyKey: string) =>
    agentTaskRunSchema.parse(
      await apiClient.post<unknown>('/agent/tasks', input, { idempotencyKey }),
    ),
  cancel: async (projectId: string, runId: string) =>
    agentTaskRunSchema.parse(
      await apiClient.post<unknown>(
        `/agent/tasks/${encodeURIComponent(runId)}/cancel?project_id=${encodeURIComponent(projectId)}`,
        {},
      ),
    ),
};
