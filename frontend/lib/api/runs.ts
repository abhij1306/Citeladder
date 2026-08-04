/**
 * Runs (audits) + executions domain endpoints (F2): launch, list, poll detail,
 * cancel, executions list + single-execution evidence, and export URLs. Run
 * progress is polling-first (`getAudit`). Every JSON response passes through
 * `strictValidate`.
 */
import { z } from 'zod';

import { API_BASE_URL, apiClient, type ApiRequestOptions } from './client';
import {
  auditEstimateSchema,
  auditScheduleSchema,
  auditSchema,
  executionEvidenceSchema,
  executionSchema,
  strictValidate,
} from './schemas';
import { definedQuery, withQuery } from './shared';
import type {
  Audit,
  AuditSchedule,
  AuditScheduleCadence,
  Execution,
  ExecutionEvidence,
  LogicalEngine,
} from './types';

const auditListSchema = z.array(auditSchema);
const executionListSchema = z.array(executionSchema);
const auditScheduleListSchema = z.array(auditScheduleSchema);

/**
 * `POST /audits` body (B5 `AuditCreate`). The workspace is resolved from the
 * `X-Workspace-Id` header, so it is not part of the body. A run measures a
 * project's prompts (a whole `prompt_set_id`, or explicit `prompt_ids`) across
 * one or more logical `engines`; provider keys are never carried here.
 */
export type LaunchAuditInput = {
  project_id: string;
  prompt_set_id?: string;
  prompt_ids?: string[];
  engines: LogicalEngine[];
  repetitions?: number;
  benchmark_mode?: string;
  measurement_mode: 'pulse' | 'benchmark';
  /** Optional 64-bit seed as a decimal string; generated + stored when omitted. */
  random_seed?: string;
};

export type AuditRepairInput = {
  provider?: string;
  engine?: string;
  prompt_id?: string;
  task_ids?: string[];
};

export type CreateAuditScheduleInput = {
  prompt_set_id: string;
  cadence: AuditScheduleCadence;
  interval_minutes?: number;
  timezone?: string;
  engines: LogicalEngine[];
  repetitions?: number;
  benchmark_mode?: string;
  measurement_mode?: 'pulse' | 'benchmark';
  enabled?: boolean;
  next_run_at?: string;
};

export const runsApi = {
  estimateAudit: async (input: LaunchAuditInput, options?: ApiRequestOptions) => {
    const res = await apiClient.post('/audits/estimate', input, options);
    return strictValidate(auditEstimateSchema, res, 'runs.estimateAudit');
  },
  launchAudit: async (input: LaunchAuditInput, options?: ApiRequestOptions) => {
    const res = await apiClient.post<Audit>('/audits', input, options);
    return strictValidate(auditSchema, res, 'runs.launchAudit');
  },
  listAudits: async (params?: { project_id?: string }, options?: ApiRequestOptions) => {
    const path = withQuery('/audits', definedQuery(params));
    const res = await apiClient.get<Audit[]>(path, options);
    return strictValidate(auditListSchema, res, 'runs.listAudits');
  },
  getAudit: async (auditId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<Audit>(`/audits/${auditId}`, options);
    return strictValidate(auditSchema, res, 'runs.getAudit');
  },
  cancelAudit: async (auditId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.post<Audit>(`/audits/${auditId}/cancel`, undefined, options);
    return strictValidate(auditSchema, res, 'runs.cancelAudit');
  },
  rerunFailures: async (
    auditId: string,
    input: AuditRepairInput = {},
    options?: ApiRequestOptions,
  ) => {
    const res = await apiClient.post<Audit>(`/audits/${auditId}/rerun-failures`, input, options);
    return strictValidate(auditSchema, res, 'runs.rerunFailures');
  },
  listSchedules: async (projectId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<AuditSchedule[]>(
      `/projects/${projectId}/audit-schedules`,
      options,
    );
    return strictValidate(auditScheduleListSchema, res, 'runs.listSchedules');
  },
  createSchedule: async (
    projectId: string,
    input: CreateAuditScheduleInput,
    options?: ApiRequestOptions,
  ) => {
    const res = await apiClient.post<AuditSchedule>(
      `/projects/${projectId}/audit-schedules`,
      input,
      options,
    );
    return strictValidate(auditScheduleSchema, res, 'runs.createSchedule');
  },
  listExecutions: async (auditId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<Execution[]>(`/audits/${auditId}/executions`, options);
    return strictValidate(executionListSchema, res, 'runs.listExecutions');
  },
  getExecution: async (executionId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<ExecutionEvidence>(`/executions/${executionId}`, options);
    return strictValidate(executionEvidenceSchema, res, 'runs.getExecution');
  },
  /** Same-origin export URLs (browser navigation / download links). */
  exportUrl: (auditId: string, format: 'csv' | 'md') =>
    `${API_BASE_URL}/audits/${auditId}/export.${format}`,
  /**
   * Same-origin SSE endpoint (optional; polling is the baseline). The backend
   * `/events` endpoint returns JSON by default and an SSE `text/event-stream`
   * only with `?stream=true`, so the streaming helper must request it.
   */
  eventsUrl: (auditId: string) => `${API_BASE_URL}/audits/${auditId}/events?stream=true`,
};
