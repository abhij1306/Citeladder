import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { mswServer } from '@/test/msw-server';
import { aiReferralsApi } from './analytics';

const projectId = '11111111-1111-4111-8111-111111111111';
const dashboard = { project_id: projectId, window_start: '2026-08-01', window_end: '2026-08-07', granularity: 'day', referral_volume: [], referral_share: [], sources: [], analyzer_version: 'ai-referrals-v2', formula_version: 'ai-referral-sessions-v2' };

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

describe('aiReferralsApi', () => {
  it('uses the focused persisted endpoint and validates its compact response', async () => {
    let requested = '';
    mswServer.use(http.get(`/api/v1/projects/${projectId}/ai-referrals`, ({ request }) => {
      requested = request.url;
      return HttpResponse.json(dashboard);
    }));
    expect(await aiReferralsApi.getDashboard(projectId, { granularity: 'day' })).toEqual(dashboard);
    expect(new URL(requested).searchParams.get('granularity')).toBe('day');
  });
});
