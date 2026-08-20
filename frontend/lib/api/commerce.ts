/** Persisted, read-only Commerce projections. */
import { apiClient, type ApiRequestOptions } from './client';
import { commerceCatalogHealthSchema, commerceComparisonSchema, strictValidate } from './schemas';
import { definedQuery, withQuery } from './shared';
import type { CommerceCatalogHealth, CommerceComparison } from './types';

export const commerceApi = {
  getCatalogHealth: async (projectId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<CommerceCatalogHealth>(
      `/projects/${projectId}/commerce/catalog-health`,
      options,
    );
    return strictValidate(commerceCatalogHealthSchema, res, 'commerce.getCatalogHealth');
  },
  getComparison: async (projectId: string, auditId?: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<CommerceComparison>(
      withQuery(`/projects/${projectId}/commerce/comparisons`, definedQuery({ audit_id: auditId })),
      options,
    );
    return strictValidate(commerceComparisonSchema, res, 'commerce.getComparison');
  },
};
