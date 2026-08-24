/**
 * Products domain endpoints (agentic commerce): catalog CRUD, CSV/JSON import,
 * and the product visibility projections — the
 * selected-audit dashboard, per-product mention evidence, and the CSV export
 * URL. Projections read persisted rows only (backend invariant 7) and default
 * to the project's latest completed audit when `audit_id` is omitted. Every
 * JSON response passes through `strictValidate`.
 */
import { z } from 'zod';

import { API_BASE_URL, apiClient, type ApiRequestOptions } from './client';
import {
  productAuditReferencesSchema,
  productEvidenceResponseSchema,
  productImportResponseSchema,
  productSchema,
  productVisibilitySchema,
  productVisibilityTrendResponseSchema,
  strictValidate,
} from './schemas';
import { definedQuery, withQuery } from './shared';
import type {
  Product,
  ProductAuditReferences,
  ProductEvidenceResponse,
  ProductImportResponse,
  ProductVisibility,
  ProductVisibilityTrend,
} from './types';

const productListSchema = z.array(productSchema);

/** `POST /projects/{id}/products` body (backend `ProductInput`). */
export type ProductInput = {
  sku: string;
  name: string;
  aliases?: string[];
  variants?: { name: string; sku?: string; price?: number | null }[];
  price?: number | null;
  // ISO-4217; the backend normalizes to uppercase.
  currency?: string;
  url?: string;
  attributes?: Record<string, unknown>;
};

export type ProductUpdateInput = Partial<ProductInput>;

/** Filters for the product mention-evidence request (all optional). */
export type ProductEvidenceParams = {
  /** Restrict to one audit in the authorized project. */
  audit_id?: string;
  /** Logical engine slice (`chatgpt` | `gemini` | `claude`); omit for all. */
  engine?: string;
  /** Newest-window size (backend default 100, max 500). */
  limit?: number;
};

/** Filters for the selected-audit product visibility projection. */
export type ProductVisibilityParams = {
  /** Restrict to one audit; omit for the latest product audit. */
  audit_id?: string;
  /** Logical engine slice; omit for the cross-engine aggregate. */
  engine?: string;
};

/** Query params for the product visibility CSV export URL. */
export type ProductVisibilityExportParams = {
  audit_id?: string;
  /** Engine slice; the export receives the on-screen engine slice. */
  engine?: string;
};

export const productsApi = {
  list: async (projectId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<Product[]>(`/projects/${projectId}/products`, options);
    return strictValidate(productListSchema, res, 'products.list');
  },
  create: async (projectId: string, input: ProductInput, options?: ApiRequestOptions) => {
    const res = await apiClient.post<Product>(`/projects/${projectId}/products`, input, options);
    return strictValidate(productSchema, res, 'products.create');
  },
  get: async (productId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<Product>(`/products/${productId}`, options);
    return strictValidate(productSchema, res, 'products.get');
  },
  update: async (productId: string, input: ProductUpdateInput, options?: ApiRequestOptions) => {
    const res = await apiClient.patch<Product>(`/products/${productId}`, input, options);
    return strictValidate(productSchema, res, 'products.update');
  },
  remove: (productId: string, options?: ApiRequestOptions) =>
    apiClient.delete<void>(`/products/${productId}`, options),
  /**
   * Multipart CSV import (D1): returns the refreshed catalog (`items`) plus
   * the per-row outcome `summary` (created/skipped counts and the reason
   * every skipped row was dropped).
   */
  importCsv: async (projectId: string, file: File, options?: ApiRequestOptions) => {
    const form = new FormData();
    form.append('file', file);
    const res = await apiClient.postForm<ProductImportResponse>(
      `/projects/${projectId}/products/import`,
      form,
      options,
    );
    return strictValidate(productImportResponseSchema, res, 'products.importCsv');
  },
  /**
   * Persist browser-parsed rows through the same `/import` endpoint (the
   * backend accepts a JSON body of `{ products: [...] }`); returns the
   * refreshed catalog (`items`, new rows carry `origin='imported'`) plus the
   * per-row outcome `summary` (D1).
   */
  importRows: async (projectId: string, rows: ProductInput[], options?: ApiRequestOptions) => {
    const res = await apiClient.post<ProductImportResponse>(
      `/projects/${projectId}/products/import`,
      { products: rows },
      options,
    );
    return strictValidate(productImportResponseSchema, res, 'products.importRows');
  },
  /**
   * Read-only delete guard (D4): how many audit configurations froze this
   * product. Advisory only — past runs keep their frozen copy, so a delete
   * is never blocked by it.
   */
  getAuditReferences: async (productId: string, options?: ApiRequestOptions) => {
    const res = await apiClient.get<ProductAuditReferences>(
      `/products/${productId}/audit-references`,
      options,
    );
    return strictValidate(productAuditReferencesSchema, res, 'products.getAuditReferences');
  },
  /**
   * Selected-audit product dashboard (defaults to the latest product audit).
   * `engine` slices entries to their persisted per-engine aggregate.
   */
  getProductVisibility: async (
    projectId: string,
    params?: ProductVisibilityParams,
    options?: ApiRequestOptions,
  ) => {
    const res = await apiClient.get<ProductVisibility>(
      withQuery(`/projects/${projectId}/products/visibility`, definedQuery(params)),
      options,
    );
    return strictValidate(productVisibilitySchema, res, 'products.getProductVisibility');
  },
  getProductVisibilityTrend: async (
    projectId: string,
    productId: string,
    engine?: string,
    options?: ApiRequestOptions,
  ) => {
    const res = await apiClient.get<ProductVisibilityTrend>(
      withQuery(
        `/projects/${projectId}/products/visibility/trends`,
        definedQuery({ product_id: productId, engine }),
      ),
      options,
    );
    return strictValidate(
      productVisibilityTrendResponseSchema,
      res,
      'products.getProductVisibilityTrend',
    );
  },
  /** Persisted mention evidence for one product (bounded, newest-first). */
  getProductEvidence: async (
    productId: string,
    params?: ProductEvidenceParams,
    options?: ApiRequestOptions,
  ) => {
    const res = await apiClient.get<ProductEvidenceResponse>(
      withQuery(`/products/${productId}/visibility/evidence`, definedQuery(params)),
      options,
    );
    return strictValidate(productEvidenceResponseSchema, res, 'products.getProductEvidence');
  },
  /**
   * Same-origin export URL (browser navigation / download link). Receives
   * the same engine slice as the on-screen projection.
   */
  exportCsvUrl: (projectId: string, params?: ProductVisibilityExportParams) =>
    withQuery(
      `${API_BASE_URL}/projects/${projectId}/products/visibility/export.csv`,
      definedQuery(params),
    ),
};
