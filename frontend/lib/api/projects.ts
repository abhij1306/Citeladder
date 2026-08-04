/**
 * Projects + workspaces domain endpoints (F2). Workspace-scoped; no `user_id`.
 * Every response passes through `strictValidate`.
 */
import { z } from 'zod';

import { apiClient, type ApiRequestOptions } from './client';
import {
  brandProfileAcceptResponseSchema,
  brandProfileSchema,
  brandProfileSuggestionSchema,
  projectSchema,
  strictValidate,
  workspaceSchema,
  commandCenterSchema,
} from './schemas';
import type {
  BrandProfile,
  BrandProfileAcceptResponse,
  BrandProfileDraft,
  BrandProfileSuggestion,
  CommandCenter,
  Project,
  Workspace,
} from './types';

const workspaceListSchema = z.array(workspaceSchema);
const projectListSchema = z.array(projectSchema);

export type ProjectInput = {
  name: string;
  brand_name: string;
  website_url: string;
  country_code: string;
  language_code: string;
  benchmark_mode: Project['benchmark_mode'];
  default_repetitions: number;
  brand: { aliases: string[] };
  owned_domains: string[];
  unintended_domains: string[];
  competitors: Array<{ name: string; aliases: string[]; domains: string[] }>;
};

export type BrandProfileField = keyof BrandProfileDraft;
export type BrandProfileUpdateInput = Partial<BrandProfileDraft>;
export type BrandProfileAcceptInput = {
  accepted_fields: BrandProfileField[];
  manual_overrides: BrandProfileUpdateInput;
};

export const projectsApi = {
  listWorkspaces: async (options?: ApiRequestOptions) => {
    const res = await apiClient.get<Workspace[]>('/workspaces', options);
    return strictValidate(workspaceListSchema, res, 'projects.listWorkspaces');
  },
  listProjects: async (options?: ApiRequestOptions) => {
    const res = await apiClient.get<Project[]>('/projects', options);
    return strictValidate(projectListSchema, res, 'projects.listProjects');
  },
  getProject: async (projectId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<Project>(`/projects/${projectId}`, options);
    return strictValidate(projectSchema, res, 'projects.getProject');
  },
  getCommandCenter: async (projectId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<CommandCenter>(
      `/projects/${projectId}/command-center`,
      options,
    );
    return strictValidate(commandCenterSchema, res, 'projects.getCommandCenter');
  },
  downloadExecutiveReport: (projectId: string, options?: ApiRequestOptions) =>
    apiClient.getBlob(`/projects/${projectId}/reports/executive.pdf`, options),
  createProject: async (input: ProjectInput, options?: ApiRequestOptions) => {
    const res = await apiClient.post<Project>('/projects', input, options);
    return strictValidate(projectSchema, res, 'projects.createProject');
  },
  updateProject: async (
    projectId: string,
    input: Partial<ProjectInput>,
    options?: ApiRequestOptions,
  ) => {
    const res = await apiClient.patch<Project>(`/projects/${projectId}`, input, options);
    return strictValidate(projectSchema, res, 'projects.updateProject');
  },
  deleteProject: (projectId: string, options?: ApiRequestOptions) =>
    apiClient.delete<void>(`/projects/${projectId}`, options),
  refreshProjectLogos: async (projectId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.post<Project>(`/projects/${projectId}/logos/refresh`, {}, options);
    return strictValidate(projectSchema, res, 'projects.refreshProjectLogos');
  },
  getBrandProfile: async (projectId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<BrandProfile>(`/projects/${projectId}/brand-profile`, options);
    return strictValidate(brandProfileSchema, res, 'projects.getBrandProfile');
  },
  updateBrandProfile: async (
    projectId: string,
    input: BrandProfileUpdateInput,
    options?: ApiRequestOptions,
  ) => {
    const res = await apiClient.put<BrandProfile>(
      `/projects/${projectId}/brand-profile`,
      input,
      options,
    );
    return strictValidate(brandProfileSchema, res, 'projects.updateBrandProfile');
  },
  suggestBrandProfile: async (
    projectId: string,
    input?: { manual_brand_context?: string },
    options?: ApiRequestOptions,
  ) => {
    const res = await apiClient.post<BrandProfileSuggestion>(
      `/projects/${projectId}/brand-profile/suggest`,
      { confirm_send_evidence: true, manual_brand_context: input?.manual_brand_context },
      options,
    );
    return strictValidate(brandProfileSuggestionSchema, res, 'projects.suggestBrandProfile');
  },
  acceptBrandProfileSuggestion: async (
    projectId: string,
    suggestionId: string,
    input: BrandProfileAcceptInput,
    options?: ApiRequestOptions,
  ) => {
    const res = await apiClient.post<BrandProfileAcceptResponse>(
      `/projects/${projectId}/brand-profile/suggestions/${suggestionId}/accept`,
      input,
      options,
    );
    return strictValidate(
      brandProfileAcceptResponseSchema,
      res,
      'projects.acceptBrandProfileSuggestion',
    );
  },
};
