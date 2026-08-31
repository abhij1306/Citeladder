import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { mswServer } from '@/test/msw-server';

import {
  PROJECT_ID,
  SET_ID,
  makeProject,
  makePrompt,
  makeSet,
  makeTopic,
  renderPromptsPage,
  setupPromptsPageTests,
  usePromptPageHandlers,
} from '@/test/fixtures/prompts';

let currentSearch = new URLSearchParams();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/prompts',
  useSearchParams: () => currentSearch,
}));

setupPromptsPageTests(() => {
  currentSearch = new URLSearchParams();
});

// Manage mode — the full PromptLibrary workspace rendered in-page, entered
// here via the `?mode=manage` deep link (set before each render).
describe('PromptsPage manage mode (PromptLibrary)', () => {
  beforeEach(() => {
    currentSearch = new URLSearchParams('mode=manage');
  });

  it('renders the prompt table with a row per prompt', async () => {
    usePromptPageHandlers([
      makePrompt(),
      makePrompt({
        id: '44444444-4444-4444-8444-444444444444',
        text: 'Nike vs Adidas',
        intent: 'comparison',
      }),
    ]);
    renderPromptsPage();

    expect(
      await screen.findByText('Best running shoes?', undefined, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(screen.getByText('Nike vs Adidas')).toBeInTheDocument();
  });

  it('shows the empty state when the set has no prompts', async () => {
    usePromptPageHandlers([]);
    renderPromptsPage();

    expect(
      await screen.findByText('No prompts yet', undefined, { timeout: 5000 }),
    ).toBeInTheDocument();
    // Both the toolbar and the empty-state card expose an "Add prompt" action.
    expect(screen.getAllByRole('button', { name: 'Add prompt' }).length).toBeGreaterThan(0);
  });

  it('generates prompts through the consent-gated dialog', async () => {
    const user = userEvent.setup();
    usePromptPageHandlers([makePrompt()], [makeTopic()]);
    let generateBody: Record<string, unknown> | null = null;
    const generated = makePrompt({
      id: '66666666-6666-4666-8666-666666666666',
      text: 'Best trail runners?',
      theme: 'Footwear',
      status: 'active',
      origin: 'generated',
      topic_id: '55555555-5555-4555-8555-555555555555',
    });
    mswServer.use(
      http.post(`/api/v1/prompt-sets/${SET_ID}/generate`, async ({ request }) => {
        generateBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            generated: [generated],
            topics: [makeTopic({ origin: 'generated', active_count: 1 })],
            dropped_duplicates: 0,
          },
          { status: 201 },
        );
      }),
    );

    renderPromptsPage();
    await screen.findByText('Best running shoes?', undefined, { timeout: 5000 });
    await user.click(screen.getByRole('button', { name: 'Generate prompts' }));

    const dialog = await screen.findByRole('dialog');
    const generateButton = within(dialog).getByRole('button', { name: 'Generate' });
    expect(generateButton).toBeEnabled();
    await user.click(generateButton);

    await waitFor(() => expect(generateBody).not.toBeNull());
    expect(generateBody).toMatchObject({ count: 10 });
    expect(generateBody).not.toHaveProperty('confirm_send_evidence');
    expect(await within(dialog).findByText(/1 prompt added to Active/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Close' }));
    expect(screen.getByRole('tab', { name: /Active/ })).toHaveAttribute('aria-selected', 'true');
  });

  it('generates starting topics and prompts when onboarding left no topics', async () => {
    const user = userEvent.setup();
    usePromptPageHandlers([makePrompt()], []);
    let generateBody: Record<string, unknown> | null = null;
    mswServer.use(
      http.post(`/api/v1/prompt-sets/${SET_ID}/generate`, async ({ request }) => {
        generateBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          { generated: [], topics: [], dropped_duplicates: 0, requested_count: 10 },
          { status: 201 },
        );
      }),
    );

    renderPromptsPage();
    await screen.findByText('Best running shoes?', undefined, { timeout: 5000 });
    await user.click(screen.getByRole('button', { name: 'Generate prompts' }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/create them from your confirmed offerings/i)).toBeVisible();
    expect(within(dialog).queryByRole('combobox', { name: 'Topic' })).toBeNull();
    const generateButton = within(dialog).getByRole('button', { name: 'Generate' });
    expect(generateButton).toBeEnabled();
    await user.click(generateButton);

    await waitFor(() => expect(generateBody).toEqual({ count: 10 }));
  });

  it('rejects fractional prompt counts', async () => {
    const user = userEvent.setup();
    usePromptPageHandlers([makePrompt()], [makeTopic()]);

    renderPromptsPage();
    await screen.findByText('Best running shoes?', undefined, { timeout: 5000 });
    await user.click(screen.getByRole('button', { name: 'Generate prompts' }));

    const dialog = await screen.findByRole('dialog');
    const count = within(dialog).getByRole('spinbutton', { name: 'Number of prompts' });
    await user.clear(count);
    await user.type(count, '1.5');

    expect(within(dialog).getByRole('button', { name: 'Generate' })).toBeDisabled();
    expect(count).toHaveAttribute('aria-invalid', 'true');
  });

  it('selects the Active tab and reports placement when generated prompts land active', async () => {
    const user = userEvent.setup();
    usePromptPageHandlers([makePrompt()], [makeTopic()]);
    const generatedActive = makePrompt({
      id: '66666666-6666-4666-8666-666666666666',
      text: 'Auto-promoted prompt',
      status: 'active',
      origin: 'generated',
    });
    mswServer.use(
      http.post(`/api/v1/prompt-sets/${SET_ID}/generate`, () =>
        HttpResponse.json(
          { generated: [generatedActive], topics: [], dropped_duplicates: 0 },
          { status: 201 },
        ),
      ),
    );

    renderPromptsPage();
    await screen.findByText('Best running shoes?', undefined, { timeout: 5000 });
    await user.click(screen.getByRole('button', { name: 'Generate prompts' }));

    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Generate' }));

    // Summary reports the Active placement.
    expect(await within(dialog).findByText(/1 prompt added to Active/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Close' }));
    // The Active tab (which holds the generated row) stays selected.
    expect(screen.getByRole('tab', { name: /Active/ })).toHaveAttribute('aria-selected', 'true');
  });

  it('shows a fresh error only, never a stale success summary, on a failed retry', async () => {
    const user = userEvent.setup();
    usePromptPageHandlers([makePrompt()], [makeTopic()]);
    const generated = makePrompt({
      id: '66666666-6666-4666-8666-666666666666',
      text: 'Best trail runners?',
      status: 'active',
      origin: 'generated',
      topic_id: '55555555-5555-4555-8555-555555555555',
    });
    // First call succeeds, the retry fails with a provider error (502).
    let calls = 0;
    mswServer.use(
      http.post(`/api/v1/prompt-sets/${SET_ID}/generate`, () => {
        calls += 1;
        if (calls === 1) {
          return HttpResponse.json(
            {
              generated: [generated],
              topics: [makeTopic({ origin: 'generated', active_count: 1 })],
              dropped_duplicates: 0,
            },
            { status: 201 },
          );
        }
        return HttpResponse.json(
          { detail: { code: 'provider_error', message: 'boom' } },
          { status: 502 },
        );
      }),
    );

    renderPromptsPage();
    await screen.findByText('Best running shoes?', undefined, { timeout: 5000 });
    await user.click(screen.getByRole('button', { name: 'Generate prompts' }));

    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Generate' }));
    expect(await within(dialog).findByText(/1 prompt added to Active/)).toBeInTheDocument();

    // Retry fails: the stale success summary must be gone, only the error shows.
    await user.click(within(dialog).getByRole('button', { name: 'Generate' }));
    expect(await within(dialog).findByText(/The AI provider call failed/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/1 prompt added to Active/)).not.toBeInTheDocument();
    expect(within(dialog).queryByText(/Generated 1 prompt/)).not.toBeInTheDocument();
  });

  it('counts only topics that received generated rows, not duplicate-only touched topics', async () => {
    const user = userEvent.setup();
    usePromptPageHandlers([makePrompt()], [makeTopic()]);
    // One generated row lands in a single topic, but the run "touched" two
    // topics (the second only had a dropped duplicate). The summary must say
    // 1 topic, not 2, and still report the dropped duplicate.
    const generated = makePrompt({
      id: '66666666-6666-4666-8666-666666666666',
      text: 'Best trail runners?',
      status: 'active',
      origin: 'generated',
      topic_id: '55555555-5555-4555-8555-555555555555',
    });
    mswServer.use(
      http.post(`/api/v1/prompt-sets/${SET_ID}/generate`, () =>
        HttpResponse.json(
          {
            generated: [generated],
            topics: [
              makeTopic({ id: '55555555-5555-4555-8555-555555555555', active_count: 1 }),
              makeTopic({
                id: '77777777-7777-4777-8777-777777777777',
                name: 'Apparel',
              }),
            ],
            dropped_duplicates: 1,
          },
          { status: 201 },
        ),
      ),
    );

    renderPromptsPage();
    await screen.findByText('Best running shoes?', undefined, { timeout: 5000 });
    await user.click(screen.getByRole('button', { name: 'Generate prompts' }));

    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Generate' }));

    // Derived from unique non-null topic_id values on `generated` (1), not the
    // two touched topics; the dropped duplicate is still reported.
    const summary = await within(dialog).findByText(/across 1 topic/);
    expect(summary).toHaveTextContent(/1 duplicate skipped/);
    expect(within(dialog).queryByText(/across 2 topics/)).not.toBeInTheDocument();
  });

  it('resets the topic filter to All topics so new rows are visible after generating', async () => {
    const user = userEvent.setup();
    const viewedTopic = makeTopic({ id: '55555555-5555-4555-8555-555555555555', active_count: 1 });
    // A generated row lands in a different topic than the one being viewed.
    const otherTopicId = '77777777-7777-4777-8777-777777777777';
    const generated = makePrompt({
      id: '66666666-6666-4666-8666-666666666666',
      text: 'Generated elsewhere prompt',
      status: 'active',
      origin: 'generated',
      topic_id: otherTopicId,
    });
    usePromptPageHandlers(
      [makePrompt({ topic_id: viewedTopic.id, text: 'Topic-scoped prompt' })],
      [viewedTopic, makeTopic({ id: otherTopicId, name: 'Apparel' })],
    );
    // After generation the prompt-set refetch includes the new active row.
    let generatedYet = false;
    mswServer.use(
      http.get('/api/v1/prompt-sets', () =>
        HttpResponse.json([
          makeSet(
            generatedYet
              ? [makePrompt({ topic_id: viewedTopic.id, text: 'Topic-scoped prompt' }), generated]
              : [makePrompt({ topic_id: viewedTopic.id, text: 'Topic-scoped prompt' })],
          ),
        ]),
      ),
      http.post(`/api/v1/prompt-sets/${SET_ID}/generate`, () => {
        generatedYet = true;
        return HttpResponse.json(
          {
            generated: [generated],
            topics: [makeTopic({ id: otherTopicId, name: 'Apparel', active_count: 1 })],
            dropped_duplicates: 0,
          },
          { status: 201 },
        );
      }),
    );

    renderPromptsPage();
    await screen.findByText('Topic-scoped prompt', undefined, { timeout: 5000 });

    // Narrow to the viewed topic first.
    await user.click(await screen.findByRole('button', { name: /^Footwear/ }));

    // Generate — the run lands the row in a different topic (Apparel).
    await user.click(screen.getByRole('button', { name: 'Generate prompts' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Generate' }));
    await within(dialog).findByText(/1 prompt added to Active/);
    await user.click(within(dialog).getByRole('button', { name: 'Close' }));

    // Topic filter reset to All topics + Active tab selected → the new row
    // is visible even though it landed in a topic the user was not viewing.
    expect(screen.getByRole('tab', { name: /Active/ })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText('Generated elsewhere prompt')).toBeInTheDocument();
  });

  it('surfaces a topic load failure in the rail', async () => {
    const set = makeSet([makePrompt()]);
    mswServer.use(
      http.get('/api/v1/projects', () => HttpResponse.json([makeProject([set])])),
      http.get('/api/v1/prompt-sets', () => HttpResponse.json([set])),
      http.get(`/api/v1/projects/${PROJECT_ID}/topics`, () =>
        HttpResponse.json({ detail: 'boom' }, { status: 400 }),
      ),
    );

    renderPromptsPage();
    await screen.findByText('Best running shoes?', undefined, { timeout: 5000 });
    expect(await screen.findAllByText(/Couldn't load topics/)).not.toHaveLength(0);
  });

  it('shows actionable config guidance when no agent is configured (503)', async () => {
    const user = userEvent.setup();
    usePromptPageHandlers([makePrompt()], [makeTopic()]);
    mswServer.use(
      http.post(`/api/v1/prompt-sets/${SET_ID}/generate`, () =>
        HttpResponse.json(
          { detail: { code: 'agent_not_configured', message: 'No default agent' } },
          { status: 503 },
        ),
      ),
    );

    renderPromptsPage();
    await screen.findByText('Best running shoes?', undefined, { timeout: 5000 });
    await user.click(screen.getByRole('button', { name: 'Generate prompts' }));

    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Generate' }));

    expect(await within(dialog).findByText(/No AI provider is configured/)).toBeInTheDocument();
    expect(within(dialog).getByText('DEFAULT_AGENT_API_KEY')).toBeInTheDocument();
  });

  it('splits prompts across active and archived tabs', async () => {
    const user = userEvent.setup();
    usePromptPageHandlers([
      makePrompt(),
      makePrompt({
        id: '77777777-7777-4777-8777-777777777777',
        text: 'Archived prompt one',
        status: 'archived',
        origin: 'generated',
      }),
    ]);

    renderPromptsPage();
    // Active tab shows only the active prompt.
    await screen.findByText('Best running shoes?', undefined, { timeout: 5000 });
    expect(screen.queryByText('Archived prompt one')).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: /Archived/ }));
    expect(screen.getByText('Archived prompt one')).toBeInTheDocument();
    expect(screen.queryByText('Best running shoes?')).not.toBeInTheDocument();
  });

  it('filters by topic from the topics rail and creates topics', async () => {
    const user = userEvent.setup();
    const topic = makeTopic({ active_count: 1 });
    usePromptPageHandlers(
      [
        makePrompt({ topic_id: topic.id, text: 'Topic-scoped prompt' }),
        makePrompt({ id: '88888888-8888-4888-8888-888888888888', text: 'Unfiled prompt' }),
      ],
      [topic],
    );
    let createdTopic: Record<string, unknown> | null = null;
    mswServer.use(
      http.post(`/api/v1/projects/${PROJECT_ID}/topics`, async ({ request }) => {
        createdTopic = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(makeTopic({ name: createdTopic.name as string }), {
          status: 201,
        });
      }),
    );

    renderPromptsPage();
    await screen.findByText('Topic-scoped prompt', undefined, { timeout: 5000 });
    expect(screen.getByText('Unfiled prompt')).toBeInTheDocument();

    // Selecting the topic narrows the table to its prompts (the accessible
    // name includes the count suffix, so match on prefix).
    await user.click(await screen.findByRole('button', { name: /^Footwear/ }));
    expect(screen.queryByText('Unfiled prompt')).not.toBeInTheDocument();
    expect(screen.getByText('Topic-scoped prompt')).toBeInTheDocument();

    // Inline add-topic form posts the new name.
    await user.click(screen.getByRole('button', { name: 'Add topic' }));
    await user.type(screen.getByRole('textbox', { name: 'Topic name' }), 'Apparel');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(createdTopic).toEqual({ name: 'Apparel' }));
  });

  it('filters by search', async () => {
    const user = userEvent.setup();
    usePromptPageHandlers([
      makePrompt(),
      makePrompt({
        id: '44444444-4444-4444-8444-444444444444',
        text: 'Nike vs Adidas',
        intent: 'comparison',
      }),
    ]);
    renderPromptsPage();

    await screen.findByText('Best running shoes?', undefined, { timeout: 5000 });
    await user.type(screen.getByRole('searchbox', { name: 'Search prompts' }), 'nike');

    expect(screen.queryByText('Best running shoes?')).not.toBeInTheDocument();
    expect(screen.getByText('Nike vs Adidas')).toBeInTheDocument();
  });

  it('creates a prompt through the add dialog', async () => {
    const user = userEvent.setup();
    usePromptPageHandlers([]);
    let created: Record<string, unknown> | null = null;
    mswServer.use(
      http.post(`/api/v1/prompt-sets/${SET_ID}/prompts`, async ({ request }) => {
        created = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(makePrompt({ text: created.text as string }), { status: 201 });
      }),
    );

    renderPromptsPage();
    await screen.findByText('No prompts yet', undefined, { timeout: 5000 });
    // The toolbar action is the first "Add prompt" button.
    await user.click(screen.getAllByRole('button', { name: 'Add prompt' })[0]);

    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByLabelText(/Prompt text/), 'Fresh prompt');
    await user.click(within(dialog).getByRole('button', { name: 'Add prompt' }));

    await waitFor(() => expect(created).not.toBeNull());
    expect(created).toMatchObject({ text: 'Fresh prompt', enabled: true });
  });

  it('toggles enabled via the row switch', async () => {
    const user = userEvent.setup();
    usePromptPageHandlers([makePrompt({ enabled: true })]);
    let patched: Record<string, unknown> | null = null;
    mswServer.use(
      http.patch('/api/v1/prompts/:id', async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(makePrompt({ enabled: false }));
      }),
    );

    renderPromptsPage();
    await screen.findByText('Best running shoes?', undefined, { timeout: 5000 });
    await user.click(screen.getByRole('switch', { name: /disable prompt/i }));

    await waitFor(() => expect(patched).toEqual({ enabled: false }));
  });

  it('deletes a prompt via the row menu', async () => {
    const user = userEvent.setup();
    usePromptPageHandlers([makePrompt()]);
    let deleted = false;
    mswServer.use(
      http.delete('/api/v1/prompts/:id', () => {
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderPromptsPage();
    await screen.findByText('Best running shoes?', undefined, { timeout: 5000 });
    await user.click(screen.getByRole('button', { name: 'Prompt actions' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Delete' }));

    await waitFor(() => expect(deleted).toBe(true));
  });

  it('parses, previews, and persists a CSV import', async () => {
    const user = userEvent.setup();
    usePromptPageHandlers([]);
    let imported: { prompts: unknown[] } | null = null;
    mswServer.use(
      http.post(`/api/v1/prompt-sets/${SET_ID}/import`, async ({ request }) => {
        imported = (await request.json()) as { prompts: unknown[] };
        return HttpResponse.json(makeSet([makePrompt({ origin: 'imported' })]), { status: 201 });
      }),
    );

    renderPromptsPage();
    await screen.findByText('No prompts yet', undefined, { timeout: 5000 });
    await user.click(screen.getByRole('button', { name: 'Import CSV' }));

    const dialog = await screen.findByRole('dialog');
    const file = new File(
      ['text,theme,intent\nBest shoes?,Comfort,discovery\n,MissingText,purchase\n'],
      'prompts.csv',
      { type: 'text/csv' },
    );
    await user.upload(within(dialog).getByLabelText('CSV file'), file);

    // Preview renders both rows; one is flagged invalid (empty text).
    expect(await within(dialog).findByText('Best shoes?')).toBeInTheDocument();
    expect(within(dialog).getByText(/1 skipped/)).toBeInTheDocument();

    // Only the valid row is importable.
    await user.click(within(dialog).getByRole('button', { name: /Import 1 prompt/ }));

    await waitFor(() => expect(imported).not.toBeNull());
    const payload = imported as { prompts: unknown[] } | null;
    if (!payload) throw new Error('import payload was not captured');
    const rows = payload.prompts;
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ text: 'Best shoes?', intent: 'discovery' });
  });
});
