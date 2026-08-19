import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ProjectProvider } from '@/lib/project/project-context';
import { mswServer } from '@/test/msw-server';

import PromptsPage from './page';

import {
  PROJECT_ID,
  SET_ID,
  TOPIC_ID,
  WORKSPACE_ID,
  makeEvidenceItem,
  makePrompt,
  makeTopic,
  renderPromptsPage,
  setupPromptsPageTests,
  usePromptPageHandlers,
} from '@/test/fixtures/prompts';

let currentSearch = new URLSearchParams();
const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));
const replaceStateSpy = vi.fn((_data: unknown, _unused: string, url?: string | URL | null) => {
  currentSearch = new URL(url?.toString() ?? '/prompts', 'http://localhost').searchParams;
});
vi.stubGlobal('history', { ...window.history, replaceState: replaceStateSpy });
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: pushMock, prefetch: vi.fn() }),
  usePathname: () => '/prompts',
  useSearchParams: () => currentSearch,
}));

setupPromptsPageTests(() => {
  currentSearch = new URLSearchParams();
  replaceStateSpy.mockClear();
  pushMock.mockClear();
});

describe('PromptsPage (Your Prompts)', () => {
  it('launches an audit in place and routes directly to the new run', async () => {
    const user = userEvent.setup();
    const auditId = '99999999-9999-4999-8999-999999999999';
    let posted: Record<string, unknown> | null = null;
    usePromptPageHandlers([makePrompt({ topic_id: TOPIC_ID })], [makeTopic()]);
    mswServer.use(
      http.get('/api/v1/provider-connections', () =>
        HttpResponse.json([
          {
            id: '88888888-8888-4888-8888-888888888888',
            workspace_id: WORKSPACE_ID,
            label: 'OpenAI',
            transport_provider: 'openai',
            base_url: null,
            active: true,
            api_key_set: true,
            last_tested_at: '2026-07-15T00:00:00Z',
            // Verified: the launch dialog only offers engines whose latest
            // probe succeeded, since that is what admission will execute.
            last_test_status: 'ok',
            routes: [
              {
                id: '77777777-7777-4777-8777-777777777777',
                logical_engine: 'chatgpt',
                transport_provider: 'openai',
                transport_model: 'gpt-5.4-nano-2026-03-17',
                is_default: true,
              },
            ],
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          },
        ]),
      ),
      http.post('/api/v1/audits/estimate', () =>
        HttpResponse.json({
          measurement_mode: 'pulse',
          retrieval_enabled: false,
          prompt_count: 1,
          engine_count: 1,
          repetition_count: 1,
          execution_count: 1,
          maximum_attempt_count: 3,
          maximum_wall_clock_seconds: 90,
          cost_status: 'complete',
          estimated_total_cost_microusd: 100,
          engines: [
            {
              logical_engine: 'chatgpt',
              transport_provider: 'openai',
              transport_model: 'gpt-5.4-nano-2026-03-17',
              retrieval_enabled: false,
              prompt_count: 1,
              repetition_count: 1,
              execution_count: 1,
              maximum_attempt_count: 3,
              estimated_input_tokens: 10,
              estimated_output_tokens: 600,
              estimated_search_calls: null,
              estimated_token_cost_microusd: 100,
              estimated_search_cost_microusd: null,
              estimated_total_cost_microusd: 100,
              cost_status: 'complete',
              pricing_version: 'official-2026-08-03',
            },
          ],
        }),
      ),
      http.post('/api/v1/audits', async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            id: auditId,
            workspace_id: WORKSPACE_ID,
            project_id: PROJECT_ID,
            status: 'queued',
            benchmark_mode: 'consumer_like',
            repetitions: 1,
            random_seed: '7',
            requested_count: 1,
            completed_count: 0,
            failed_count: 0,
            error_message: '',
            engine_snapshots: [],
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
            started_at: null,
            completed_at: null,
          },
          { status: 201 },
        );
      }),
    );
    renderPromptsPage();

    await user.click(await screen.findByRole('button', { name: 'Launch audit' }));
    const dialog = await screen.findByRole('dialog', { name: 'Launch an audit' });
    await user.click(within(dialog).getByRole('checkbox', { name: 'ChatGPT' }));
    await user.click(within(dialog).getByRole('button', { name: 'Launch audit' }));

    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted).toMatchObject({
      project_id: PROJECT_ID,
      prompt_set_id: SET_ID,
      engines: ['chatgpt'],
    });
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith(`/runs/${auditId}`));
  });

  it('groups active prompts by topic with a summary banner and a manage link', async () => {
    usePromptPageHandlers(
      [
        makePrompt({ topic_id: TOPIC_ID }),
        makePrompt({
          id: '44444444-4444-4444-8444-444444444444',
          text: 'Ungrouped prompt',
        }),
        // Archived prompts never appear on Your Prompts.
        makePrompt({
          id: '66666666-6666-4666-8666-666666666666',
          text: 'Archived prompt',
          status: 'archived',
        }),
      ],
      [makeTopic()],
    );
    renderPromptsPage();

    expect(
      await screen.findByText('Best running shoes?', undefined, { timeout: 5000 }),
    ).toBeInTheDocument();
    // Banner counts only active prompts (2) and topics with prompts (1).
    expect(screen.getByText('2')).toBeInTheDocument();
    // The banner's manage link enters the in-page manage mode deep link.
    expect(screen.getByRole('link', { name: 'Manage prompts' })).toHaveAttribute(
      'href',
      '/prompts?mode=manage',
    );
    // Topic group header + ungrouped bucket.
    expect(screen.getAllByText('Footwear').length).toBeGreaterThan(0);
    expect(screen.getByText('Ungrouped')).toBeInTheDocument();
    expect(screen.queryByText('Archived prompt')).not.toBeInTheDocument();
  });

  it('collapses a topic group when its expander is toggled', async () => {
    const user = userEvent.setup();
    usePromptPageHandlers([makePrompt({ topic_id: TOPIC_ID })], [makeTopic()]);
    renderPromptsPage();

    await screen.findByText('Best running shoes?', undefined, { timeout: 5000 });
    await user.click(screen.getByRole('button', { name: 'Collapse topic Footwear' }));
    expect(screen.queryByText('Best running shoes?')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Expand topic Footwear' }));
    expect(screen.getByText('Best running shoes?')).toBeInTheDocument();
  });

  it('derives per-prompt visibility scores from persisted evidence', async () => {
    const promptId = '33333333-3333-4333-8333-333333333333';
    usePromptPageHandlers(
      [makePrompt({ topic_id: TOPIC_ID })],
      [makeTopic()],
      [
        makeEvidenceItem(promptId, true, 'bbbbbbbb-0000-4000-8000-000000000001'),
        makeEvidenceItem(promptId, true, 'bbbbbbbb-0000-4000-8000-000000000002'),
        makeEvidenceItem(promptId, false, 'bbbbbbbb-0000-4000-8000-000000000003'),
      ],
    );
    renderPromptsPage();

    await screen.findByText('Best running shoes?', undefined, { timeout: 5000 });
    // 2 of 3 executions mentioned the brand → 67%, on both the prompt row and
    // the single-prompt topic group row.
    expect(await screen.findAllByText('67%')).toHaveLength(2);
  });

  it('shows the empty state pointing to manage mode when no active prompts exist', async () => {
    usePromptPageHandlers([]);
    renderPromptsPage();

    expect(
      await screen.findByText('No active prompts yet', undefined, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /Manage prompts/ }).length).toBeGreaterThan(0);
  });

  it('filters prompts by search', async () => {
    const user = userEvent.setup();
    usePromptPageHandlers([
      makePrompt(),
      makePrompt({ id: '44444444-4444-4444-8444-444444444444', text: 'Nike vs Adidas' }),
    ]);
    renderPromptsPage();

    await screen.findByText('Best running shoes?', undefined, { timeout: 5000 });
    await user.type(screen.getByRole('searchbox', { name: 'Search prompts' }), 'nike');

    expect(screen.queryByText('Best running shoes?')).not.toBeInTheDocument();
    expect(screen.getByText('Nike vs Adidas')).toBeInTheDocument();
  });

  it('enters manage mode from the deep link and exits via the in-page control', async () => {
    const user = userEvent.setup();
    currentSearch = new URLSearchParams('mode=manage');
    usePromptPageHandlers([makePrompt({ topic_id: TOPIC_ID })], [makeTopic()]);
    const { rerender } = renderPromptsPage();

    expect(
      await screen.findByRole('button', { name: /Generate prompts & topics/ }, { timeout: 5000 }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Done managing' }));
    rerender(
      <ProjectProvider>
        <PromptsPage />
      </ProjectProvider>,
    );
    expect(
      await screen.findByText(/configuration includes/, undefined, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Manage prompts' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Manage prompts' })).toHaveAttribute(
      'href',
      '/prompts?mode=manage',
    );

    const manageLink = screen.getByRole('link', { name: 'Manage prompts' });
    manageLink.addEventListener('click', (event) => event.preventDefault(), { once: true });
    await user.click(manageLink);
    currentSearch = new URLSearchParams('mode=manage');
    rerender(
      <ProjectProvider>
        <PromptsPage />
      </ProjectProvider>,
    );
    expect(await screen.findByRole('button', { name: 'Done managing' })).toBeInTheDocument();
  });

  it('clears the ?mode=manage param when leaving manage mode so manage links stay live', async () => {
    const user = userEvent.setup();
    currentSearch = new URLSearchParams('mode=manage');
    usePromptPageHandlers([makePrompt({ topic_id: TOPIC_ID })], [makeTopic()]);
    renderPromptsPage();

    // Deep-linked into manage mode.
    expect(
      await screen.findByRole('button', { name: /Generate prompts & topics/ }, { timeout: 5000 }),
    ).toBeInTheDocument();

    // Exiting clears the URL param (the read view's manage links point at
    // /prompts?mode=manage and would no-op against the current URL).
    await user.click(screen.getByRole('button', { name: 'Done managing' }));
    expect(replaceStateSpy).toHaveBeenCalledWith(null, '', '/prompts');
  });
});
