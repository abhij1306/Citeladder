import type { SiteHealthOverview } from '@/lib/api/types';

export const EMPTY_WEB_FUNDAMENTALS: SiteHealthOverview['web_fundamentals'] = {
  state: 'not_measured',
  areas: [],
  field_data: {
    state: 'unavailable',
    reason: 'provider_not_configured',
    lcp: null,
    inp: null,
    cls: null,
  },
  source_analysis_ids: [],
  source_artifact_ids: [],
  source_evaluation_ids: [],
  limitations: [],
};
