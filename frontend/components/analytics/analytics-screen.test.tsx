import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

import type { Project } from '@/lib/api/types';
import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';

const PROJECT = '88888888-8888-4888-8888-888888888888';
const activeProject = { id: PROJECT, workspace_id: '11111111-1111-4111-8111-111111111111' } as Project;

vi.mock('@/lib/project/project-context', () => ({
  useProjectContext: () => ({ activeProject, isLoading: false }),
}));

import { AnalyticsScreen } from './analytics-screen';

const endpoint = `/api/v1/projects/${PROJECT}/ai-referrals`;
const dashboard = {
  project_id: PROJECT,
  window_start: '2026-07-20',
  window_end: '2026-07-22',
  granularity: 'day',
  referral_volume: [
    { date: '2026-07-20', value: 4 },
    { date: '2026-07-21', value: 1 },
    { date: '2026-07-22', value: 2 },
  ],
  referral_share: [
    { date: '2026-07-20', value: 0.4 },
    { date: '2026-07-21', value: 0.1 },
    { date: '2026-07-22', value: null },
  ],
  sources: [
    { ai_source: 'chatgpt', sessions: 4, share: 0.2 },
    { ai_source: 'gemini', sessions: 1, share: 0.05 },
  ],
  analyzer_version: 'ai-referrals-v2',
  formula_version: 'ai-referral-sessions-v2',
};

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

describe('AnalyticsScreen — focused AI Referrals', () => {
  it('renders only persisted referral measurement, without visibility or event drill-downs', async () => {
    mswServer.use(http.get(endpoint, () => HttpResponse.json(dashboard)));
    renderWithProviders(<AnalyticsScreen />);

    expect(await screen.findByText('AI-referred sessions')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Share of GA4 sessions' })).toBeInTheDocument();
    expect(screen.getByText('AI referral sources')).toBeInTheDocument();
    expect(screen.getByText('ChatGPT')).toBeInTheDocument();
    expect(screen.getByText('20.0%')).toBeInTheDocument();
    expect(screen.queryByText(/Cross-engine visibility/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/correlation/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/AI-referral events/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/theme/i)).not.toBeInTheDocument();
  });

  it('shows the honest measured-zero state without fabricating a source', async () => {
    mswServer.use(
      http.get(endpoint, () =>
        HttpResponse.json({
          ...dashboard,
          referral_volume: dashboard.referral_volume.map((point) => ({ ...point, value: 0 })),
          referral_share: dashboard.referral_share.map((point) => ({ ...point, value: 0 })),
          sources: [],
        }),
      ),
    );
    renderWithProviders(<AnalyticsScreen />);

    expect(
      await screen.findByText(/no sessions matched a known AI source in this window/i),
    ).toBeInTheDocument();
    expect(screen.queryByText('Other')).not.toBeInTheDocument();
  });

  it('distinguishes incomplete classification from measured zero', async () => {
    mswServer.use(
      http.get(endpoint, () =>
        HttpResponse.json({
          ...dashboard,
          referral_volume: dashboard.referral_volume.map((point) => ({ ...point, value: null })),
          referral_share: dashboard.referral_share.map((point) => ({ ...point, value: null })),
          sources: [],
        }),
      ),
    );
    renderWithProviders(<AnalyticsScreen />);
    expect(
      await screen.findByText(/classification is not complete for this window/i),
    ).toBeInTheDocument();
  });

  it('keeps the chart and keyboard focus while the interval refetches', async () => {
    let releaseMonth: ((response: Response) => void) | undefined;
    mswServer.use(
      http.get(endpoint, ({ request }) => {
        if (new URL(request.url).searchParams.get('granularity') !== 'month') {
          return HttpResponse.json(dashboard);
        }
        return new Promise<Response>((resolve) => {
          releaseMonth = resolve;
        });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<AnalyticsScreen />);

    expect(await screen.findAllByText('3 days')).toHaveLength(2);
    const month = screen.getByRole('radio', { name: 'Month' });
    await user.click(month);

    expect(month).toHaveFocus();
    expect(screen.getByRole('status')).toHaveTextContent('Updating data… Previous data shown.');
    expect(screen.getAllByText('3 days')).toHaveLength(2);

    releaseMonth?.(
      HttpResponse.json({
        ...dashboard,
        granularity: 'month',
        referral_volume: [{ date: '2026-07-20', value: 7 }],
        referral_share: [{ date: '2026-07-20', value: 0.35 }],
      }),
    );
    await waitFor(() => expect(screen.getByRole('status')).toBeEmptyDOMElement());
    expect(screen.getAllByText('1 month')).toHaveLength(2);
  });
});
