import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { queryKeys } from '@/lib/api/query-keys';
import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';

import RunDetailPage from './page';

const AUDIT_ID = '44444444-4444-4444-8444-444444444444';
const WORKSPACE_ID = '22222222-2222-4222-8222-222222222222';
const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
const EXEC_ID = '77777777-7777-4777-8777-777777777777';
let currentSearchParams = new URLSearchParams();

vi.mock('next/navigation', () => ({
  useParams: () => ({ runId: AUDIT_ID }),
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => currentSearchParams,
}));

function audit(overrides: Record<string, unknown> = {}) {
  return {
    id: AUDIT_ID,
    workspace_id: WORKSPACE_ID,
    project_id: PROJECT_ID,
    status: 'running',
    benchmark_mode: 'consumer_like',
    repetitions: 3,
    random_seed: '7',
    requested_count: 6,
    completed_count: 4,
    failed_count: 1,
    error_message: '',
    engine_snapshots: [],
    created_at: '2026-07-15T00:00:00Z',
    updated_at: '2026-07-15T00:00:00Z',
    started_at: '2026-07-15T00:00:05Z',
    completed_at: null,
    ...overrides,
  };
}

function execution(overrides: Record<string, unknown> = {}) {
  return {
    id: EXEC_ID,
    audit_id: AUDIT_ID,
    prompt_index: 0,
    repetition: 1,
    randomized_position: 0,
    logical_engine: 'gemini',
    transport_provider: 'google',
    transport_model: 'gemini-flash-latest',
    status: 'succeeded',
    attempt_count: 1,
    max_attempts: 5,
    prompt_text: 'Which CRM is best for a growing team?',
    answer_text: 'An answer',
    search_used: true,
    error_code: '',
    error_detail: '',
    latency_ms: 1200,
    created_at: '2026-07-15T00:00:00Z',
    completed_at: '2026-07-15T00:00:03Z',
    ...overrides,
  };
}

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
beforeEach(() => {
  currentSearchParams = new URLSearchParams();
});
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

describe('RunDetailPage', () => {
  it('renders the progress panel counts + status and the executions table', async () => {
    mswServer.use(
      http.get(`/api/v1/audits/${AUDIT_ID}`, () => HttpResponse.json(audit())),
      http.get(`/api/v1/audits/${AUDIT_ID}/executions`, () => HttpResponse.json([execution()])),
    );

    renderWithProviders(<RunDetailPage />);

    expect(await screen.findByText('Running')).toBeInTheDocument();
    // Counts.
    expect(screen.getByText('6')).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument();
    // Executions table row with the engine + an in-context evidence action.
    const row = (await screen.findByText('Gemini')).closest('tr')!;
    expect(within(row).getByText('Succeeded')).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: 'Evidence' })).toBeInTheDocument();
  });

  it('shows the humanized audit error detail when the initial run request fails', async () => {
    mswServer.use(
      http.get(`/api/v1/audits/${AUDIT_ID}`, () =>
        HttpResponse.json({ detail: 'This run is no longer available.' }, { status: 404 }),
      ),
      http.get(`/api/v1/audits/${AUDIT_ID}/executions`, () => HttpResponse.json([])),
    );

    renderWithProviders(<RunDetailPage />);

    expect(await screen.findByText('This run is no longer available.')).toBeInTheDocument();
  });

  it('keeps the running audit and executions mounted during background refetches', async () => {
    let auditCalls = 0;
    let executionCalls = 0;
    let releaseAudit: (() => void) | undefined;
    let releaseExecutions: (() => void) | undefined;
    mswServer.use(
      http.get(`/api/v1/audits/${AUDIT_ID}`, async () => {
        auditCalls += 1;
        if (auditCalls > 1) {
          await new Promise<void>((resolve) => {
            releaseAudit = resolve;
          });
        }
        return HttpResponse.json(audit());
      }),
      http.get(`/api/v1/audits/${AUDIT_ID}/executions`, async () => {
        executionCalls += 1;
        if (executionCalls > 1) {
          await new Promise<void>((resolve) => {
            releaseExecutions = resolve;
          });
        }
        return HttpResponse.json([execution()]);
      }),
    );

    const { queryClient } = renderWithProviders(<RunDetailPage />);
    expect(await screen.findByText('Running')).toBeInTheDocument();
    expect(await screen.findByText('Gemini')).toBeInTheDocument();

    const refetches = Promise.all([
      queryClient.refetchQueries({ queryKey: queryKeys.runs.detail(AUDIT_ID), exact: true }),
      queryClient.refetchQueries({ queryKey: queryKeys.runs.executions(AUDIT_ID), exact: true }),
    ]);
    await waitFor(() => {
      expect(releaseAudit).toBeTypeOf('function');
      expect(releaseExecutions).toBeTypeOf('function');
    });

    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(screen.getByText('Gemini')).toBeInTheDocument();
    expect(screen.queryByText(/Could not load this run/)).not.toBeInTheDocument();
    expect(screen.queryByText('Could not load executions.')).not.toBeInTheDocument();

    releaseAudit?.();
    releaseExecutions?.();
    await refetches;
  });

  it('keeps the last good run and executions visible after failed background refetches', async () => {
    let failRefetch = false;
    mswServer.use(
      http.get(`/api/v1/audits/${AUDIT_ID}`, () =>
        failRefetch
          ? HttpResponse.json({ detail: 'temporary failure' }, { status: 400 })
          : HttpResponse.json(audit()),
      ),
      http.get(`/api/v1/audits/${AUDIT_ID}/executions`, () =>
        failRefetch
          ? HttpResponse.json({ detail: 'temporary failure' }, { status: 400 })
          : HttpResponse.json([execution()]),
      ),
    );

    const { queryClient } = renderWithProviders(<RunDetailPage />);
    expect(await screen.findByText('Running')).toBeInTheDocument();
    expect(await screen.findByText('Gemini')).toBeInTheDocument();

    failRefetch = true;
    await Promise.all([
      queryClient.refetchQueries({ queryKey: queryKeys.runs.detail(AUDIT_ID), exact: true }),
      queryClient.refetchQueries({ queryKey: queryKeys.runs.executions(AUDIT_ID), exact: true }),
    ]);

    expect(queryClient.getQueryState(queryKeys.runs.detail(AUDIT_ID))?.status).toBe('error');
    expect(queryClient.getQueryState(queryKeys.runs.executions(AUDIT_ID))?.status).toBe('error');
    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(screen.getByText('Gemini')).toBeInTheDocument();
    expect(screen.queryByText(/Could not load this run/)).not.toBeInTheDocument();
    expect(screen.queryByText('Could not load executions.')).not.toBeInTheDocument();
  });

  it('opens execution evidence in a drawer without navigating away', async () => {
    const user = userEvent.setup();
    mswServer.use(
      http.get(`/api/v1/audits/${AUDIT_ID}`, () =>
        HttpResponse.json(audit({ status: 'completed' })),
      ),
      http.get(`/api/v1/audits/${AUDIT_ID}/executions`, () => HttpResponse.json([execution()])),
      http.get(`/api/v1/executions/${EXEC_ID}`, () =>
        HttpResponse.json({
          id: EXEC_ID,
          analysis_id: '88888888-8888-4888-8888-888888888888',
          audit_id: AUDIT_ID,
          task_id: EXEC_ID,
          artifact_id: null,
          analyzer_version: 'v1',
          scoring_rule_version: 'v1',
          logical_engine: 'gemini',
          transport_provider: 'google',
          transport_model: 'gemini-flash-latest',
          prompt_index: 0,
          repetition: 1,
          prompt_class: 'unbranded',
          brand_mentioned: true,
          brand_first_offset: 0,
          owned_domain_cited: true,
          owned_citation_count: 1,
          unintended_domain_cited: false,
          citation_count: 1,
          search_used: true,
          search_query_count: 0,
          sentiment: null,
          avg_position: null,
          score: { visibility: 1 },
          citations: [
            {
              ordinal: 1,
              url: 'https://acme.example/research',
              title: 'Acme research',
              domain: 'acme.example',
              classification: 'owned',
              is_owned: true,
              is_unintended: false,
              matched_competitor: null,
            },
          ],
          competitors_mentioned: ['Beta'],
          created_at: '2026-07-15T00:00:03Z',
        }),
      ),
    );

    renderWithProviders(<RunDetailPage />);
    await user.click(await screen.findByRole('button', { name: 'Evidence' }));

    const evidenceDrawer = await screen.findByRole('dialog');
    expect(evidenceDrawer).toHaveTextContent('Execution evidence');
    expect(evidenceDrawer).toHaveClass('sm:max-w-220');
    expect(await screen.findByText('An answer')).toBeInTheDocument();
    expect(screen.getByText('Why it scored this way')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Acme research/ })).toHaveAttribute(
      'href',
      'https://acme.example/research',
    );
  });

  it('reacts to an execution deep-link query after mount', async () => {
    mswServer.use(
      http.get(`/api/v1/audits/${AUDIT_ID}`, () =>
        HttpResponse.json(audit({ status: 'completed' })),
      ),
      http.get(`/api/v1/audits/${AUDIT_ID}/executions`, () => HttpResponse.json([execution()])),
      http.get(`/api/v1/executions/${EXEC_ID}`, () =>
        HttpResponse.json({
          id: EXEC_ID,
          analysis_id: '88888888-8888-4888-8888-888888888888',
          audit_id: AUDIT_ID,
          task_id: EXEC_ID,
          artifact_id: null,
          analyzer_version: 'v1',
          scoring_rule_version: 'v1',
          logical_engine: 'gemini',
          transport_provider: 'google',
          transport_model: 'gemini-flash-latest',
          prompt_index: 0,
          repetition: 1,
          prompt_class: 'unbranded',
          brand_mentioned: true,
          brand_first_offset: 0,
          owned_domain_cited: false,
          owned_citation_count: 0,
          unintended_domain_cited: false,
          citation_count: 0,
          search_used: true,
          search_query_count: 0,
          sentiment: null,
          avg_position: null,
          score: { visibility: 1 },
          citations: [],
          competitors_mentioned: [],
          created_at: '2026-07-15T00:00:03Z',
        }),
      ),
    );

    const view = renderWithProviders(<RunDetailPage />);
    expect(await screen.findByText('Gemini')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    currentSearchParams = new URLSearchParams(`execution=${EXEC_ID}`);
    view.rerender(<RunDetailPage />);

    expect(await screen.findByRole('dialog')).toHaveTextContent('Execution evidence');
    expect(await screen.findByText('An answer')).toBeInTheDocument();
  });

  it('cancels an active run via POST /audits/{id}/cancel', async () => {
    const user = userEvent.setup();
    let cancelled = false;
    mswServer.use(
      http.get(`/api/v1/audits/${AUDIT_ID}`, () =>
        HttpResponse.json(audit(cancelled ? { status: 'cancelled' } : {})),
      ),
      http.get(`/api/v1/audits/${AUDIT_ID}/executions`, () => HttpResponse.json([execution()])),
      http.post(`/api/v1/audits/${AUDIT_ID}/cancel`, () => {
        cancelled = true;
        return HttpResponse.json(
          audit({ status: 'cancelled', completed_at: '2026-07-15T00:05:00Z' }),
        );
      }),
    );

    renderWithProviders(<RunDetailPage />);

    const cancelButton = await screen.findByRole('button', { name: /cancel run/i });
    await user.click(cancelButton);

    // The run flips to cancelled and the cancel button becomes disabled (terminal).
    expect(await screen.findByText('Cancelled')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: /cancel run/i })).toBeDisabled());
  });

  it('exposes CSV/MD export links', async () => {
    mswServer.use(
      http.get(`/api/v1/audits/${AUDIT_ID}`, () =>
        HttpResponse.json(audit({ status: 'completed' })),
      ),
      http.get(`/api/v1/audits/${AUDIT_ID}/executions`, () => HttpResponse.json([execution()])),
    );

    renderWithProviders(<RunDetailPage />);

    const csv = await screen.findByRole('link', { name: /export csv/i });
    expect(csv).toHaveAttribute('href', `/api/v1/audits/${AUDIT_ID}/export.csv`);
    expect(screen.getByRole('link', { name: /export md/i })).toHaveAttribute(
      'href',
      `/api/v1/audits/${AUDIT_ID}/export.md`,
    );
  });
});
