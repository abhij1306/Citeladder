/**
 * AI Referrals query-key namespace — isolated by project; every requested
 * window and granularity participates in the key.
 */
import type { ListFilters } from './shared';

export const aiReferralsKeys = {
  all: ['ai-referrals'] as const,
  dashboard: (projectId: string, filters: ListFilters = {}) =>
    ['ai-referrals', 'dashboard', projectId, filters] as const,
};
