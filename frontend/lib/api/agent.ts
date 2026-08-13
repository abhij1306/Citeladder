/** Strict client for the two bounded Growth Agent tasks and their evidence attempts. */
import { z } from 'zod';

import { apiClient, type ApiRequestOptions } from './client';

export const agentTaskTypeSchema = z.enum(['explain', 'build_roadmap']);

const artifactReferenceSchema = z.object({
  kind: z.string(),
  id: z.string(),
});

const omissionSchema = z.record(z.string(), z.unknown());

export const agentToolAttemptSchema = z.object({
  id: z.uuid(),
  run_attempt: z.number().int(),
  ordinal: z.number().int(),
  tool_name: z.string(),
  tool_version: z.string(),
  status: z.string(),
  input: z.record(z.string(), z.unknown()),
  artifact_refs: z.array(artifactReferenceSchema),
  output_hash: z.string(),
  omissions: z.array(omissionSchema),
  error_code: z.string(),
  retryable: z.boolean(),
  latency_ms: z.number().int(),
  created_at: z.string(),
});

const agentResultSchema = z.object({
  answer: z.string(),
  limitations: z.array(z.string()),
  artifact_refs: z.array(artifactReferenceSchema),
});

export const agentTaskRunSchema = z.object({
  id: z.uuid(),
  project_id: z.uuid(),
  task_type: agentTaskTypeSchema,
  objective: z.string(),
  task_policy_version: z.string(),
  status: z.string(),
  result: agentResultSchema.nullable(),
  provider_adapter: z.string(),
  endpoint_host: z.string(),
  model: z.string(),
  instruction_version: z.string(),
  usage: z.record(z.string(), z.number().int()).nullable(),
  latency_ms: z.number().int().nullable(),
  error_code: z.string(),
  error_detail: z.string(),
  attempt_count: z.number().int(),
  completed_at: z.string().nullable(),
  cancelled_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  attempts: z.array(agentToolAttemptSchema),
});

export type AgentTaskType = z.infer<typeof agentTaskTypeSchema>;
export type AgentToolAttempt = z.infer<typeof agentToolAttemptSchema>;
export type AgentTaskRun = z.infer<typeof agentTaskRunSchema>;

export type AgentTaskInput = {
  project_id: string;
  task_type: AgentTaskType;
  objective: string;
};

export const agentApi = {
  listTasks: async (projectId: string, options?: ApiRequestOptions) =>
    z
      .array(agentTaskRunSchema)
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
