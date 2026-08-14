import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { mswServer } from '@/test/msw-server';
import { aiReferralsApi, type AiReferralsWindowParams } from './ai-referrals';

const projectId = '11111111-1111-4111-8111-111111111111';
const dashboard = {
  project_id: projectId,
  window_start: '2026-08-01',
  window_end: '2026-08-07',
  granularity: 'day',
  referral_volume: [],
  referral_share: [],
  sources: [],
  analyzer_version: 'ai-referrals-v2',
  formula_version: 'ai-referral-sessions-v2',
};

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

describe('aiReferralsApi', () => {
  it('requires both date-window bounds at the type boundary', () => {
    const bounded = { from: '2026-08-01', to: '2026-08-07' } satisfies AiReferralsWindowParams;
    const latest = { granularity: 'week' } satisfies AiReferralsWindowParams;
    expect(bounded).toEqual({ from: '2026-08-01', to: '2026-08-07' });
    expect(latest).toEqual({ granularity: 'week' });

    // @ts-expect-error A persisted window is exact and must provide both bounds.
    const missingTo: AiReferralsWindowParams = { from: '2026-08-01' };
    expect(missingTo).toEqual({ from: '2026-08-01' });
  });

  it('uses the focused persisted endpoint and validates its compact response', async () => {
    let requested = '';
    mswServer.use(
      http.get(`/api/v1/projects/${projectId}/ai-referrals`, ({ request }) => {
        requested = request.url;
        return HttpResponse.json(dashboard);
      }),
    );
    expect(await aiReferralsApi.getDashboard(projectId, { granularity: 'day' })).toEqual(dashboard);
    expect(new URL(requested).searchParams.get('granularity')).toBe('day');
  });

  it('rejects impossible source totals from a drifted response', async () => {
    mswServer.use(
      http.get(`/api/v1/projects/${projectId}/ai-referrals`, () =>
        HttpResponse.json({
          ...dashboard,
          sources: [{ ai_source: 'chatgpt', sessions: -1, share: 1.1 }],
        }),
      ),
    );

    await expect(aiReferralsApi.getDashboard(projectId)).rejects.toThrow();
  });
});
