/**
 * Opportunities query-key namespace — isolated by project / filter so a
 * catalog page for one filter combination never collides with another, and a
 * recompute invalidates the whole namespace at once (`opportunityKeys.all`).
 */
import type { ListFilters } from './shared';

export const opportunityKeys = {
  all: ['opportunities'] as const,
  list: (projectId: string, filters: ListFilters = {}) =>
    ['opportunities', 'list', projectId, filters] as const,
  detail: (opportunityId: string) => ['opportunities', 'detail', opportunityId] as const,
  summary: (projectId: string) => ['opportunities', 'summary', projectId] as const,
  implementationEvents: (projectId: string, opportunityId?: string) =>
    ['opportunities', 'implementation-events', projectId, opportunityId ?? null] as const,
  implementationEvent: (projectId: string, eventId: string) =>
    ['opportunities', 'implementation-events', projectId, eventId] as const,
};
