/** Typed Commerce catalog, discovery, prompt, and AI Shelf client. */
import { z } from 'zod';

import { apiClient, type ApiRequestOptions } from './client';
import { COMMERCE_BUYER_PROMPT_REQUEST_TIMEOUT_MS } from '@/lib/config/operational';
import { strictValidate } from './schemas';
import {
  buyerPromptSchema,
  catalogImportSchema,
  commerceCategorySchema,
  commerceCatalogSchema,
  competitorDiscoverySchema,
  competitorDiscoveryTaskSchema,
  commerceProductSchema,
  competitorCandidateSchema,
  shelfSchema,
  type CommerceTarget,
  type CommerceCategoryEdit,
  type CommerceProductEdit,
} from './schemas/commerce-suite';

const path = (projectId: string, suffix: string) => `/projects/${projectId}/commerce/${suffix}`;

export const commerceApi = {
  catalog: async (projectId: string, options?: ApiRequestOptions) =>
    strictValidate(
      commerceCatalogSchema,
      await apiClient.get(path(projectId, 'catalog'), options),
      'commerce.catalog',
    ),
  importCatalog: async (projectId: string, content: string, filename = 'catalog.csv') =>
    strictValidate(
      catalogImportSchema,
      await apiClient.post(path(projectId, 'catalog/import'), {
        filename,
        content_type: 'text/csv',
        content,
      }),
      'commerce.importCatalog',
    ),
  editProduct: async (projectId: string, productId: string, body: CommerceProductEdit) =>
    strictValidate(
      commerceProductSchema,
      await apiClient.patch(path(projectId, `catalog/products/${productId}`), body),
      'commerce.editProduct',
    ),
  editCategory: async (projectId: string, categoryId: string, body: CommerceCategoryEdit) =>
    strictValidate(
      commerceCategorySchema,
      await apiClient.patch(path(projectId, `catalog/categories/${categoryId}`), body),
      'commerce.editCategory',
    ),
  competitors: async (projectId: string, options?: ApiRequestOptions) =>
    strictValidate(
      z.array(competitorCandidateSchema),
      await apiClient.get(path(projectId, 'competitors'), options),
      'commerce.competitors',
    ),
  discoverCompetitors: async (projectId: string, targets: CommerceTarget[]) =>
    strictValidate(
      competitorDiscoverySchema,
      await apiClient.post(path(projectId, 'competitors/discover'), { targets }),
      'commerce.discoverCompetitors',
    ),
  /**
   * Discovery task status. Omitting `taskIds` asks the server for whatever is
   * still in flight for the project — the only form a page reload can recover
   * from, since ids held in component state do not survive one.
   */
  competitorDiscoveries: async (
    projectId: string,
    taskIds?: string[],
    options?: ApiRequestOptions,
  ) => {
    const query = (taskIds ?? []).map((id) => `task_ids=${encodeURIComponent(id)}`).join('&');
    return strictValidate(
      z.array(competitorDiscoveryTaskSchema),
      await apiClient.get(
        `${path(projectId, 'competitors/discoveries')}${query ? `?${query}` : ''}`,
        options,
      ),
      'commerce.competitorDiscoveries',
    );
  },
  decideCompetitor: async (
    projectId: string,
    candidateId: string,
    decision: 'approved' | 'rejected',
  ) =>
    strictValidate(
      competitorCandidateSchema,
      await apiClient.patch(path(projectId, `competitors/${candidateId}`), { decision }),
      'commerce.decideCompetitor',
    ),
  buyerPrompts: async (projectId: string, options?: ApiRequestOptions) =>
    strictValidate(
      z.array(buyerPromptSchema),
      await apiClient.get(path(projectId, 'buyer-prompts'), options),
      'commerce.buyerPrompts',
    ),
  generateBuyerPrompts: async (projectId: string, targets: CommerceTarget[], count: number) =>
    strictValidate(
      z.array(buyerPromptSchema),
      await apiClient.post(
        path(projectId, 'buyer-prompts/generate'),
        { targets, count },
        { timeoutMs: COMMERCE_BUYER_PROMPT_REQUEST_TIMEOUT_MS },
      ),
      'commerce.generateBuyerPrompts',
    ),
  addBuyerPrompt: async (projectId: string, target: CommerceTarget, text: string) =>
    strictValidate(
      buyerPromptSchema,
      await apiClient.post(path(projectId, 'buyer-prompts/manual'), { target, text }),
      'commerce.addBuyerPrompt',
    ),
  decideBuyerPrompt: async (projectId: string, promptId: string, approved: boolean) =>
    strictValidate(
      buyerPromptSchema,
      await apiClient.patch(path(projectId, `buyer-prompts/${promptId}`), { approved }),
      'commerce.decideBuyerPrompt',
    ),
  shelf: async (
    projectId: string,
    target: CommerceTarget,
    auditId?: string,
    options?: ApiRequestOptions,
  ) =>
    strictValidate(
      shelfSchema,
      await apiClient.get(
        `${path(projectId, 'ai-shelf')}?target_kind=${target.kind}&target_id=${encodeURIComponent(target.id)}${auditId ? `&audit_id=${encodeURIComponent(auditId)}` : ''}`,
        options,
      ),
      'commerce.shelf',
    ),
};
