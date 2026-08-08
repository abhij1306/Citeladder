/**
 * Site Health query-key namespace — isolated by project / crawl / filter so an
 * inventory query for one crawl (or one filter combination) never collides
 * with another.
 */
import type { ListFilters } from './shared';

export const siteHealthKeys = {
  all: ['site-health'] as const,
  // Entitlement data depends on the `X-Workspace-Id` header (F5's active
  // workspace), so the workspace id must be part of the key — otherwise a
  // workspace switch would silently serve the previous workspace's cached
  // plan/quota until an unrelated invalidation happened to evict it.
  entitlements: (workspaceId: string | null) =>
    ['site-health', 'entitlements', workspaceId ?? 'default'] as const,
  dashboard: (projectId: string, crawlId?: string) =>
    ['site-health', 'dashboard', projectId, crawlId ?? 'latest'] as const,
  crawls: (projectId: string, filters: ListFilters = {}) =>
    ['site-health', 'crawls', projectId, filters] as const,
  crawl: (crawlId: string) => ['site-health', 'crawl', crawlId] as const,
  preview: (projectId: string, content: string) =>
    ['site-health', 'preview', projectId, content] as const,
  inventory: (crawlId: string, filters: ListFilters = {}) =>
    ['site-health', 'inventory', crawlId, filters] as const,
  monitored: (projectId: string) => ['site-health', 'monitored', projectId] as const,
  pages: (crawlId: string, filters: ListFilters = {}) =>
    ['site-health', 'pages', crawlId, filters] as const,
  page: (crawlId: string, siteUrlId: string) =>
    ['site-health', 'page', crawlId, siteUrlId] as const,
  issueHistory: (crawlId: string, siteUrlId: string, filters: ListFilters = {}) =>
    ['site-health', 'issue-history', crawlId, siteUrlId, filters] as const,
  issues: (crawlId: string, filters: ListFilters = {}) =>
    ['site-health', 'issues', crawlId, filters] as const,
  issue: (crawlId: string, issueId: string, filters: ListFilters = {}) =>
    ['site-health', 'issue', crawlId, issueId, filters] as const,
  events: (crawlId: string) => ['site-health', 'events', crawlId] as const,
};

/**
 * Site Intelligence keys — scoped by project AND crawl so switching the shared
 * crawl selector re-fetches every panel instead of showing another crawl's
 * frozen snapshot under the new selection.
 */
export const siteIntelligenceKeys = {
  all: ['site-intelligence'] as const,
  overview: (projectId: string, crawlId?: string) =>
    ['site-intelligence', 'overview', projectId, crawlId ?? 'latest'] as const,
  entities: (projectId: string, crawlId?: string, entityTypeId?: string) =>
    [
      'site-intelligence',
      'entities',
      projectId,
      crawlId ?? 'latest',
      entityTypeId ?? 'all',
    ] as const,
  assertions: (projectId: string, crawlId?: string, predicateId?: string) =>
    [
      'site-intelligence',
      'assertions',
      projectId,
      crawlId ?? 'latest',
      predicateId ?? 'all',
    ] as const,
  contradictions: (projectId: string, crawlId?: string) =>
    ['site-intelligence', 'contradictions', projectId, crawlId ?? 'latest'] as const,
  relations: (projectId: string, crawlId?: string) =>
    ['site-intelligence', 'relations', projectId, crawlId ?? 'latest'] as const,
  schemaGraph: (projectId: string, crawlId?: string) =>
    ['site-intelligence', 'schema', projectId, crawlId ?? 'latest'] as const,
};
