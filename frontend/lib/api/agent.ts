/** Strict client for persisted Growth Agent task runs and capability catalogs. */
import { z } from 'zod';

import { apiClient, type ApiRequestOptions } from './client';

const catalogTaskSchema = z.object({
  task_type: z.string(),
  title: z.string(),
  description: z.string(),
  allowed_tools: z.array(z.string()),
  required_scope: z.array(z.string()),
  requested_outputs: z.array(z.string()),
  max_steps: z.number().int(),
  max_tool_calls: z.number().int(),
});

const toolSchema = z.object({
  name: z.string(),
  version: z.string(),
  domain: z.string(),
  kind: z.string(),
  description: z.string(),
  idempotent: z.boolean(),
  external_effect: z.boolean(),
  maximum_result_items: z.number().int(),
});

const capabilitiesSchema = z.object({
  configured: z.boolean(),
  provider_adapter: z.string(),
  endpoint_host: z.string(),
  model: z.string(),
  model_capabilities: z.record(z.string(), z.unknown()),
  policy_version: z.string(),
  context_policy_version: z.string(),
  tool_registry_version: z.string(),
  task_catalog: z.array(catalogTaskSchema),
  tool_catalog: z.array(toolSchema),
});

const stepSchema = z.object({
  id: z.string().uuid(),
  ordinal: z.number().int(),
  name: z.string(),
  tool_name: z.string(),
  tool_version: z.string(),
  tool_kind: z.string(),
  status: z.string(),
  input: z.record(z.string(), z.unknown()),
  output: z.record(z.string(), z.unknown()).nullable(),
  child_task_kind: z.string(),
  child_task_id: z.string().uuid().nullable(),
  retry_count: z.number().int(),
  error_code: z.string(),
  error_detail: z.string(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
});

const contextSchema = z.object({
  id: z.string().uuid(),
  project_id: z.string().uuid(),
  brief_id: z.string().uuid().nullable(),
  task_type: z.string(),
  manifest: z.record(z.string(), z.unknown()),
  rendered_context: z.record(z.string(), z.unknown()),
  omissions: z.array(z.unknown()),
  selection_policy_version: z.string(),
  manifest_hash: z.string(),
  char_count: z.number().int(),
  created_at: z.string(),
});

export const agentTaskRunSchema = z.object({
  id: z.string().uuid(),
  project_id: z.string().uuid(),
  conversation_id: z.string().uuid().nullable(),
  parent_run_id: z.string().uuid().nullable(),
  context_package_id: z.string().uuid().nullable(),
  task_type: z.string(),
  objective: z.string(),
  requested_outputs: z.array(z.unknown()),
  task_policy_version: z.string(),
  allowed_tools: z.array(z.unknown()),
  resource_scope: z.record(z.string(), z.unknown()),
  industry_pack_id: z.string(),
  industry_pack_version: z.string(),
  status: z.string(),
  plan: z.array(z.unknown()),
  result: z.record(z.string(), z.unknown()).nullable(),
  validation: z.record(z.string(), z.unknown()).nullable(),
  decisions: z.array(z.unknown()),
  provider_adapter: z.string(),
  endpoint_host: z.string(),
  model: z.string(),
  capability_snapshot: z.record(z.string(), z.unknown()),
  instruction_version: z.string(),
  skill_version: z.string(),
  usage: z.record(z.string(), z.unknown()).nullable(),
  latency_ms: z.number().int().nullable(),
  error_code: z.string(),
  error_detail: z.string(),
  completed_at: z.string().nullable(),
  cancelled_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  steps: z.array(stepSchema),
  context: contextSchema.nullable(),
});

export type AgentCapabilities = z.infer<typeof capabilitiesSchema>;
export type AgentTaskRun = z.infer<typeof agentTaskRunSchema>;

export type AgentTaskInput = {
  project_id: string;
  task_type: string;
  objective: string;
  resource_scope: Record<string, unknown>;
};

export const agentApi = {
  capabilities: async (options?: ApiRequestOptions) =>
    capabilitiesSchema.parse(await apiClient.get<unknown>('/agent/capabilities', options)),
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
  decide: async (projectId: string, runId: string, decision: string, confirmed: boolean) =>
    agentTaskRunSchema.parse(
      await apiClient.post<unknown>(
        `/agent/tasks/${encodeURIComponent(runId)}/decision?project_id=${encodeURIComponent(projectId)}`,
        { decision, confirmed },
      ),
    ),
  cancel: async (projectId: string, runId: string) =>
    agentTaskRunSchema.parse(
      await apiClient.post<unknown>(
        `/agent/tasks/${encodeURIComponent(runId)}/cancel?project_id=${encodeURIComponent(projectId)}`,
        {},
      ),
    ),
};
