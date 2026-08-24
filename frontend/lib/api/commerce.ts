/** Persisted, read-only Commerce projections. */
import { apiClient, type ApiRequestOptions } from './client';
import { commerceCatalogHealthSchema, strictValidate } from './schemas';
import type { CommerceCatalogHealth } from './types';

export const commerceApi = {
  getCatalogHealth: async (projectId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<CommerceCatalogHealth>(
      `/projects/${projectId}/commerce/catalog-health`,
      options,
    );
    return strictValidate(commerceCatalogHealthSchema, res, 'commerce.getCatalogHealth');
  },
};
