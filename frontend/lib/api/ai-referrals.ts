/** Strict client for the persisted AI-referral projection. */
import type { z } from 'zod';

import { apiClient, type ApiRequestOptions } from './client';
import { aiReferralsSchema, aiSourceSchema, strictValidate } from './schemas';
import { definedQuery, withQuery } from './shared';
import type { SnapshotGranularity } from './traffic';

export type AiReferrals = z.infer<typeof aiReferralsSchema>;
export type AiSource = z.infer<typeof aiSourceSchema>;

export type AiReferralsWindow = { from: string; to: string } | { from?: never; to?: never };

export type AiReferralsWindowParams = AiReferralsWindow & {
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
