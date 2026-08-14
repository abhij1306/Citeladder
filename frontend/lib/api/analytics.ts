/** Strict client for the persisted AI-referral projection. */
import type { z } from 'zod';

import { apiClient, type ApiRequestOptions } from './client';
import { aiReferralsSchema, aiSourceSchema, strictValidate } from './schemas';
import { definedQuery, withQuery } from './shared';
import type { SnapshotGranularity } from './traffic';

export type AiReferrals = z.infer<typeof aiReferralsSchema>;
export type AiSource = z.infer<typeof aiSourceSchema>;

export type AiReferralsWindowParams = {
  from?: string;
  to?: string;
  granularity?: SnapshotGranularity;
};

export const aiReferralsApi = {
  getDashboard: async (
    projectId: string,
    params?: AiReferralsWindowParams,
    options?: ApiRequestOptions,
  ) => {
    const path = withQuery(`/projects/${projectId}/ai-referrals`, definedQuery(params));
    const response = await apiClient.get<AiReferrals>(path, options);
    return strictValidate(aiReferralsSchema, response, 'aiReferrals.getDashboard');
  },
};
