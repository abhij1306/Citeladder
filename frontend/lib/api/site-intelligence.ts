/**
 * Site Intelligence transport + query options (S2/S3).
 *
 * Kept beside `site-health.ts` rather than inside it: the URL family is shared
 * (`/site-health` stays for compatibility while the navigation label becomes
 * Site Intelligence), but these are read-only projections of a frozen snapshot
 * with no mutations, no streaming, and no export — a different shape of module.
 *
 * Every endpoint renders PERSISTED state. None of them triggers a crawl, a
 * fetch, or a recomputation, so all of them are safe to poll and safe to render
 * for a historical crawl.
 */
import { queryOptions } from '@tanstack/react-query';

import { apiClient, type ApiRequestOptions } from './client';
import { queryKeys } from './query-keys';
import {
  contradictionPageSchema,
  correctionItemSchema,
  intelligenceOverviewSchema,
  knowledgeAssertionPageSchema,
  knowledgeEntityPageSchema,
  knowledgeRelationPageSchema,
  schemaGraphResponseSchema,
  strictValidate,
} from './schemas';
import { definedQuery, withQuery } from './shared';
import type {
  ContradictionPage,
  CorrectionItem,
  IntelligenceOverview,
  KnowledgeAssertionPage,
  KnowledgeEntityPage,
  KnowledgeRelationPage,
  SchemaGraphResponse,
} from './types';

/** Omitted `crawl_id` means "the project's most recent crawl". */
type CrawlScoped = { crawlId?: string };

export type CorrectionCreateInput = {
  target_kind: 'entity' | 'assertion' | 'relation';
  target_id: string;
  value: string | number | boolean | Record<string, unknown>;
  effective_scope?: 'project' | 'entity';
  effective_scope_id?: string;
  effective_from?: string;
  effective_to?: string;
  unit?: string;
  currency?: string;
  reason: string;
};

export const siteIntelligenceApi = {
  getOverview: async (
    projectId: string,
    { crawlId }: CrawlScoped = {},
    options?: ApiRequestOptions,
  ) => {
    const path = withQuery(
      `/projects/${projectId}/site-intelligence`,
      definedQuery({ crawl_id: crawlId }),
    );
    const res = await apiClient.get<IntelligenceOverview>(path, options);
    return strictValidate(intelligenceOverviewSchema, res, 'siteIntelligence.getOverview');
  },

  getEntities: async (
    projectId: string,
    { crawlId, entityTypeId }: CrawlScoped & { entityTypeId?: string } = {},
    options?: ApiRequestOptions,
  ) => {
    const path = withQuery(
      `/projects/${projectId}/knowledge/entities`,
      definedQuery({ crawl_id: crawlId, entity_type_id: entityTypeId }),
    );
    const res = await apiClient.get<KnowledgeEntityPage>(path, options);
    return strictValidate(knowledgeEntityPageSchema, res, 'siteIntelligence.getEntities');
  },

  getAssertions: async (
    projectId: string,
    { crawlId, predicateId }: CrawlScoped & { predicateId?: string } = {},
    options?: ApiRequestOptions,
  ) => {
    const path = withQuery(
      `/projects/${projectId}/knowledge/assertions`,
      definedQuery({ crawl_id: crawlId, predicate_id: predicateId }),
    );
    const res = await apiClient.get<KnowledgeAssertionPage>(path, options);
    return strictValidate(knowledgeAssertionPageSchema, res, 'siteIntelligence.getAssertions');
  },

  getContradictions: async (
    projectId: string,
    { crawlId }: CrawlScoped = {},
    options?: ApiRequestOptions,
  ) => {
    const path = withQuery(
      `/projects/${projectId}/knowledge/contradictions`,
      definedQuery({ crawl_id: crawlId }),
    );
    const res = await apiClient.get<ContradictionPage>(path, options);
    return strictValidate(contradictionPageSchema, res, 'siteIntelligence.getContradictions');
  },

  getRelations: async (
    projectId: string,
    { crawlId }: CrawlScoped = {},
    options?: ApiRequestOptions,
  ) => {
    const path = withQuery(
      `/projects/${projectId}/knowledge/relations`,
      definedQuery({ crawl_id: crawlId }),
    );
    const res = await apiClient.get<KnowledgeRelationPage>(path, options);
    return strictValidate(knowledgeRelationPageSchema, res, 'siteIntelligence.getRelations');
  },

  getSchemaGraph: async (
    projectId: string,
    { crawlId }: CrawlScoped = {},
    options?: ApiRequestOptions,
  ) => {
    const path = withQuery(
      `/projects/${projectId}/site-intelligence/schema`,
      definedQuery({ crawl_id: crawlId }),
    );
    const res = await apiClient.get<SchemaGraphResponse>(path, options);
    return strictValidate(schemaGraphResponseSchema, res, 'siteIntelligence.getSchemaGraph');
  },

  createCorrection: async (projectId: string, input: CorrectionCreateInput) => {
    const res = await apiClient.post<CorrectionItem>(
      `/projects/${projectId}/knowledge/corrections`,
      input,
    );
    return strictValidate(correctionItemSchema, res, 'siteIntelligence.createCorrection');
  },

  withdrawCorrection: async (projectId: string, correctionId: string, reason: string) => {
    const res = await apiClient.post<CorrectionItem>(
      `/projects/${projectId}/knowledge/corrections/${correctionId}/withdraw`,
      { reason },
    );
    return strictValidate(correctionItemSchema, res, 'siteIntelligence.withdrawCorrection');
  },
};

export const siteIntelligenceQueries = {
  overview: (projectId: string, crawlId?: string) =>
    queryOptions({
      queryKey: queryKeys.siteIntelligence.overview(projectId, crawlId),
      queryFn: ({ signal }) => siteIntelligenceApi.getOverview(projectId, { crawlId }, { signal }),
    }),
  entities: (projectId: string, crawlId?: string, entityTypeId?: string) =>
    queryOptions({
      queryKey: queryKeys.siteIntelligence.entities(projectId, crawlId, entityTypeId),
      queryFn: ({ signal }) =>
        siteIntelligenceApi.getEntities(projectId, { crawlId, entityTypeId }, { signal }),
    }),
  assertions: (projectId: string, crawlId?: string, predicateId?: string) =>
    queryOptions({
      queryKey: queryKeys.siteIntelligence.assertions(projectId, crawlId, predicateId),
      queryFn: ({ signal }) =>
        siteIntelligenceApi.getAssertions(projectId, { crawlId, predicateId }, { signal }),
    }),
  contradictions: (projectId: string, crawlId?: string) =>
    queryOptions({
      queryKey: queryKeys.siteIntelligence.contradictions(projectId, crawlId),
      queryFn: ({ signal }) =>
        siteIntelligenceApi.getContradictions(projectId, { crawlId }, { signal }),
    }),
  relations: (projectId: string, crawlId?: string) =>
    queryOptions({
      queryKey: queryKeys.siteIntelligence.relations(projectId, crawlId),
      queryFn: ({ signal }) => siteIntelligenceApi.getRelations(projectId, { crawlId }, { signal }),
    }),
  schemaGraph: (projectId: string, crawlId?: string) =>
    queryOptions({
      queryKey: queryKeys.siteIntelligence.schemaGraph(projectId, crawlId),
      queryFn: ({ signal }) =>
        siteIntelligenceApi.getSchemaGraph(projectId, { crawlId }, { signal }),
    }),
};
