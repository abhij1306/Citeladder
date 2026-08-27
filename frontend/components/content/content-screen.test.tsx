import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';

import { ProjectProvider } from '@/lib/project/project-context';
import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';

import { ContentScreen } from './content-screen';

const WORKSPACE = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const PROJECT = '11111111-1111-4111-8111-111111111111';
const GEN = '33333333-3333-4333-8333-333333333333';

const project = {
  id: PROJECT,
  workspace_id: WORKSPACE,
  name: 'Acme',
  brand_name: 'Acme',
  website_url: 'https://acme.com',
  country_code: 'US',
  language_code: 'en',
  industry: 'Software',
  subindustry: 'Analytics',
  primary_market: 'US',
  benchmark_mode: 'consumer_like',
  default_repetitions: 3,
  brand: { aliases: [] },
  owned_domains: [],
  unintended_domains: [],
  competitors: [],
  prompt_sets: [],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function generation(overrides: Record<string, unknown> = {}) {
  return {
    id: GEN,
    project_id: PROJECT,
    status: 'queued',
    output_type: 'website_page',
    skill_id: 'article',
    opportunity_id: null,
    feedback: null,
    feedback_reason: '',
    feedback_at: null,
    grounding_status: 'included',
    requested_model: 'mistral-small-latest',
    returned_model: null,
    provider: 'mistral',
    created_at: '2026-07-15T00:00:00Z',
    updated_at: '2026-07-15T00:00:00Z',
    completed_at: null,
    error_code: '',
    prompt_preview: 'Write a landing page',
    prompt: 'Write a landing page for Acme.',
    grounding_summary: {
      version: 'content-context-v1',
      crawl_page_count: 3,
      crawl_urls: ['https://acme.test/', 'https://acme.test/pricing', 'https://acme.test/about'],
      crawl_completed_at: '2026-07-15T00:00:00Z',
      brand_fields: ['description'],
      search_connected: false,
      omissions: [],
    },
    finish_reason: null,
    output_truncated: false,
    output_text: null,
    usage: null,
    latency_ms: null,
    error_detail: '',
    generator_version: 'content-v1',
    skill_version: 'content-v1',
    ...overrides,
  };
}

const succeededGen = generation({
  status: 'succeeded',
  returned_model: 'mistral-small-2506',
  finish_reason: 'stop',
  output_text: '# About Acme\n\nWe make things.',
  usage: { total_tokens: 30 },
  latency_ms: 420,
  completed_at: '2026-07-15T00:01:00Z',
});

/** A bounded stand-in for the server-owned skill catalog. */
const skillCatalog = {
  version: 'content-skills-v2',
  default_skill_id: 'content_page',
  skills: [
    {
      id: 'content_page',
      label: 'Website content page',
      channel: 'web',
      description: 'A publish-ready page spec.',
      structure: ['The final H1.'],
      tone: 'Clear and specific.',
      length_hint: '500–800 words.',
    },
    {
      id: 'article',
      label: 'Article',
      channel: 'web',
      description: 'Authoritative long-form piece.',
      structure: ['A specific H1.'],
      tone: 'Expert.',
      length_hint: '900–1400 words.',
    },
    {
      id: 'blog',
      label: 'Blog post',
      channel: 'web',
      description: 'Answer-first post with worked examples.',
      structure: ['H1 phrased as a search.'],
      tone: 'Conversational.',
      length_hint: '600–900 words.',
    },
    {
      id: 'linkedin',
      label: 'LinkedIn post',
      channel: 'social',
      description: 'Professional post carrying one idea.',
      structure: ['An opening line.'],
      tone: 'Professional.',
      length_hint: '150–300 words.',
    },
  ],
};

function mockBase(listItems: Record<string, unknown>[] = []) {
  mswServer.use(
    http.get('/api/v1/projects', () => HttpResponse.json([project])),
    http.get('/api/v1/content/skills', () => HttpResponse.json(skillCatalog)),
    http.get('/api/v1/content/context-preview', () =>
      HttpResponse.json({
        crawl_available: true,
        crawl_page_count: 8,
        crawl_completed_at: '2026-07-15T00:00:00Z',
        brand_fields: ['description'],
        search_connected: false,
      }),
    ),
    http.get('/api/v1/content/generations', () => HttpResponse.json(listItems)),
    // ProjectProvider kicks off a background logo refresh; stubbed so it does
    // not surface as an unhandled request in longer-running tests.
    http.post(`/api/v1/projects/${PROJECT}/logos/refresh`, () => HttpResponse.json({})),
  );
}

function renderScreen(props: { demandSignalId?: string } = {}) {
  return renderWithProviders(
    <ProjectProvider>
      <ContentScreen demandSignalId={props.demandSignalId} />
    </ProjectProvider>,
  );
}

const DEMAND_SIGNAL = '77777777-7777-4777-8777-777777777777';

/** Latest demand snapshot carrying one striking-distance signal. */
const demandSnapshot = {
  id: '88888888-8888-4888-8888-888888888888',
  project_id: PROJECT,
  window_start: '2026-07-01',
  window_end: '2026-07-07',
  source_hash: 'hash',
  prior_snapshot_id: null,
  source_artifact_ids: [],
  source_metric_row_ids: [],
  coverage: { search: 'observed' },
  summary: {},
  comparison: null,
  formula_version: 'v1',
  analyzer_version: 'v1',
  created_at: '2026-07-08T00:00:00Z',
  signals: [
    {
      id: DEMAND_SIGNAL,
      snapshot_id: '88888888-8888-4888-8888-888888888888',
      signal_type: 'striking_distance',
      state: 'active',
      topic_cluster: 'ai marketing tools',
      page_url: 'https://acme.com/ai-tools',
      evidence: { target_kind: 'query', target: 'ai marketing tools' },
      metrics: { impressions: 250, clicks: 12, ctr: 0.048, position: 7.2 },
      coverage: {},
      limitations: [],
      priority_score: 85,
      priority_inputs: {},
      created_at: '2026-07-08T00:00:00Z',
    },
  ],
};

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

describe('ContentScreen — search demand handoff', () => {
  it('arrives from a demand signal with a written brief instead of an empty box', async () => {
    mockBase();
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/demand/latest`, () =>
        HttpResponse.json(demandSnapshot),
      ),
    );
    renderScreen({ demandSignalId: DEMAND_SIGNAL });

    const box = (await screen.findByRole('textbox', {
      name: /describe the website content/i,
    })) as HTMLTextAreaElement;
    await waitFor(() => expect(box.value).toContain('ai marketing tools'));

    const brief = box.value;
    // A query signal asks for NEW content built to rank, not a page rewrite.
    expect(brief).toContain('built to rank for the search query "ai marketing tools"');
    expect(brief).toContain('To rank for it, the content must:');
    expect(brief).not.toContain('Rewrite the existing page');
    expect(brief).toContain('Impressions: 250');
    expect(brief).toContain('Average position: 7.2');
    expect(brief).toContain('Write on behalf of Acme.');
    // Query signals default to the blog skill.
    await waitFor(() =>
      expect(screen.getByRole('radio', { name: /Blog post/i })).toHaveAttribute(
        'aria-checked',
        'true',
      ),
    );
    // Provenance is visible, and Generate is immediately available.
    expect(screen.getByText(/Brief written from the search demand signal/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Generate' })).toBeEnabled();
  });

  it('writes a corrective rewrite brief when the signal names an existing URL', async () => {
    mockBase();
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/demand/latest`, () =>
        HttpResponse.json({
          ...demandSnapshot,
          signals: [
            {
              ...demandSnapshot.signals[0],
              signal_type: 'property_relative_ctr_gap',
              evidence: { target_kind: 'page', target: 'https://acme.com/ai-tools' },
              metrics: { impressions: 900, clicks: 4, ctr: 0.004, cohort_median_ctr: 0.031 },
            },
          ],
        }),
      ),
    );
    renderScreen({ demandSignalId: DEMAND_SIGNAL });

    const box = (await screen.findByRole('textbox', {
      name: /describe the website content/i,
    })) as HTMLTextAreaElement;
    await waitFor(() => expect(box.value).toContain('Rewrite the existing page'));

    const brief = box.value;
    // The known defect drives named, specific corrections.
    expect(brief).toContain('https://acme.com/ai-tools');
    expect(brief).toContain('What is wrong with it:');
    expect(brief).toContain('Fix these specific things:');
    expect(brief).toContain('Rewrite the meta title');
    expect(brief).toContain('current route');
    // Both sides of the observed CTR gap are quoted.
    expect(brief).toContain('Click-through rate: 0.4%');
    expect(brief).toContain('Median click-through rate for this position band: 3.1%');
    // A URL fix is page work.
    await waitFor(() =>
      expect(screen.getByRole('radio', { name: /Website content page/i })).toHaveAttribute(
        'aria-checked',
        'true',
      ),
    );
  });

  it('never quotes a metric the signal did not carry', async () => {
    mockBase();
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/demand/latest`, () =>
        HttpResponse.json({
          ...demandSnapshot,
          signals: [{ ...demandSnapshot.signals[0], metrics: { impressions: 250 } }],
        }),
      ),
    );
    renderScreen({ demandSignalId: DEMAND_SIGNAL });

    const box = (await screen.findByRole('textbox', {
      name: /describe the website content/i,
    })) as HTMLTextAreaElement;
    await waitFor(() => expect(box.value).toContain('Impressions: 250'));

    const brief = box.value;
    expect(brief).not.toContain('Clicks:');
    expect(brief).not.toContain('Average position:');
    expect(brief).not.toContain('Click-through rate:');
  });

  it('distinguishes a failed demand fetch from a genuinely missing signal', async () => {
    mockBase();
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/demand/latest`, () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    renderScreen({ demandSignalId: DEMAND_SIGNAL });

    // Telling the user the signal is gone would send them to rebuild work
    // that still exists — the request failed, the signal did not vanish.
    expect(
      await screen.findByText(/Search demand could not be loaded/i, {}, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/no longer in the latest snapshot/i)).not.toBeInTheDocument();
  });

  it('explains the handoff failure when the signal is no longer in the snapshot', async () => {
    mockBase();
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/demand/latest`, () =>
        HttpResponse.json({ ...demandSnapshot, signals: [] }),
      ),
    );
    renderScreen({ demandSignalId: DEMAND_SIGNAL });

    expect(await screen.findByText(/no longer in the latest snapshot/i)).toBeInTheDocument();
  });
});

describe('ContentScreen — platform skills', () => {
  it('defaults to the catalog default and sends the platform the user picks', async () => {
    mockBase();
    const sent: Record<string, unknown>[] = [];
    mswServer.use(
      http.post('/api/v1/content/generations', async ({ request }) => {
        sent.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(generation(), { status: 201 });
      }),
      http.get(`/api/v1/content/generations/${GEN}`, () => HttpResponse.json(generation())),
    );
    renderScreen();

    // The website content page is preselected — no hardcoded 'article'.
    const pageOption = await screen.findByRole('radio', { name: /Website content page/i });
    await waitFor(() => expect(pageOption).toHaveAttribute('aria-checked', 'true'));

    // Picking a platform switches the skill sent with the generation.
    await userEvent.click(screen.getByRole('radio', { name: /LinkedIn post/i }));
    expect(screen.getByRole('radio', { name: /LinkedIn post/i })).toHaveAttribute(
      'aria-checked',
      'true',
    );

    await userEvent.type(
      screen.getByRole('textbox', { name: /describe the website content/i }),
      'Announce the new pricing',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Generate' }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].skill_id).toBe('linkedin');
  });

  it('groups the catalog by channel so platforms are discoverable', async () => {
    mockBase();
    renderScreen();

    expect(await screen.findByText('Web')).toBeInTheDocument();
    expect(screen.getByText('Social')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Article/i })).toBeInTheDocument();
  });
});

describe('ContentScreen — ready state', () => {
  it('disables Generate until a prompt is typed and names its available context', async () => {
    mockBase();
    renderScreen();
    const generate = await screen.findByRole('button', { name: 'Generate' });
    expect(generate).toBeDisabled();

    // The indicator is live: it names what will actually ground the draft,
    // and reports an unconnected optional source neutrally, not as a fault.
    expect(await screen.findByText(/website crawl · 8 pages available/i)).toBeInTheDocument();
    expect(screen.getByText(/search console · not connected/i)).toBeInTheDocument();

    await userEvent.type(
      screen.getByRole('textbox', { name: /describe the website content/i }),
      'Write a landing page',
    );
    expect(generate).toBeEnabled();
  });

  it('shows the no-project state with a /projects link when there is no project', async () => {
    mswServer.use(http.get('/api/v1/projects', () => HttpResponse.json([])));
    renderScreen();
    const link = await screen.findByRole('link', { name: /go to projects/i });
    expect(link).toHaveAttribute('href', '/projects');
    expect(screen.queryByRole('button', { name: 'Generate' })).not.toBeInTheDocument();
  });
});

describe('ContentScreen — generate flow', () => {
  it('enqueues, shows the generating panel with Cancel, then renders the result with provenance', async () => {
    let detailCalls = 0;
    mockBase();
    mswServer.use(
      http.post('/api/v1/content/generations', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        expect(body.project_id).toBe(PROJECT);
        expect(body).not.toHaveProperty('website_context_enabled');
        return HttpResponse.json(generation(), { status: 201 });
      }),
      http.get(`/api/v1/content/generations/${GEN}`, () => {
        detailCalls += 1;
        return HttpResponse.json(detailCalls < 2 ? generation() : succeededGen);
      }),
    );
    renderScreen();

    await userEvent.type(
      await screen.findByRole('textbox', { name: /describe the website content/i }),
      'Write a landing page',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Generate' }));

    // Generating: status region + Cancel, composer locked.
    expect(await screen.findByRole('status', { name: /generating content/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: /describe the website content/i })).toBeDisabled();
    for (const option of screen.getAllByRole('radio')) {
      expect(option).toBeDisabled();
      expect(option).toHaveClass('disabled:cursor-not-allowed', 'disabled:opacity-50');
    }

    // Result (poll flips to succeeded): markdown + provenance + actions.
    expect(
      await screen.findByRole('heading', { level: 1, name: 'About Acme' }, { timeout: 5000 }),
    ).toBeInTheDocument();
    // Model ids are provenance on the row, not something the writer needs on
    // the page; the footer says only what the draft was grounded with.
    expect(screen.queryByText(/requested model/i)).not.toBeInTheDocument();
    expect(screen.getByText(/grounded with: website crawl · 3 pages/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /regenerate/i })).toBeInTheDocument();
    expect(screen.queryByText(/hit the length limit/i)).not.toBeInTheDocument();
  });

  it('renders the truncation warning when output_truncated is true', async () => {
    mockBase();
    mswServer.use(
      http.post('/api/v1/content/generations', () =>
        HttpResponse.json(generation(), { status: 201 }),
      ),
      http.get(`/api/v1/content/generations/${GEN}`, () =>
        HttpResponse.json({ ...succeededGen, output_truncated: true, finish_reason: 'length' }),
      ),
    );
    renderScreen();
    await userEvent.type(
      await screen.findByRole('textbox', { name: /describe the website content/i }),
      'Long page',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Generate' }));
    expect(await screen.findByText(/hit the length limit/i)).toBeInTheDocument();
  });

  it('copies the raw markdown to the clipboard', async () => {
    mockBase();
    mswServer.use(
      http.post('/api/v1/content/generations', () =>
        HttpResponse.json(generation(), { status: 201 }),
      ),
      http.get(`/api/v1/content/generations/${GEN}`, () => HttpResponse.json(succeededGen)),
    );
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    renderScreen();
    await userEvent.type(
      await screen.findByRole('textbox', { name: /describe the website content/i }),
      'Page',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Generate' }));
    await userEvent.click(await screen.findByRole('button', { name: /copy/i }));
    expect(writeText).toHaveBeenCalledWith('# About Acme\n\nWe make things.');
  });

  it('cancel calls the cancel endpoint and leaves the generating state', async () => {
    let cancelled = false;
    mockBase();
    mswServer.use(
      http.post('/api/v1/content/generations', () =>
        HttpResponse.json(generation(), { status: 201 }),
      ),
      http.get(`/api/v1/content/generations/${GEN}`, () =>
        HttpResponse.json(
          cancelled ? generation({ status: 'cancelled', error_code: 'cancelled' }) : generation(),
        ),
      ),
      http.post(`/api/v1/content/generations/${GEN}/cancel`, () => {
        cancelled = true;
        return HttpResponse.json(generation({ status: 'cancelled', error_code: 'cancelled' }));
      }),
    );
    renderScreen();
    await userEvent.type(
      await screen.findByRole('textbox', { name: /describe the website content/i }),
      'Page',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Generate' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(cancelled).toBe(true);
    await waitFor(() =>
      expect(screen.queryByRole('status', { name: /generating/i })).not.toBeInTheDocument(),
    );
  });
});

describe('ContentScreen — error state', () => {
  it('shows the provider-not-configured 409 message and Dismiss preserves the prompt', async () => {
    mockBase();
    mswServer.use(
      http.post('/api/v1/content/generations', () =>
        HttpResponse.json({ detail: 'provider_not_configured' }, { status: 409 }),
      ),
    );
    renderScreen();
    const textarea = await screen.findByRole('textbox', {
      name: /describe the website content/i,
    });
    await userEvent.type(textarea, 'My prompt text');

    await userEvent.click(screen.getByRole('button', { name: 'Generate' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/not configured/i);

    await userEvent.click(screen.getByRole('button', { name: /dismiss/i }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    // Prompt is preserved and the composer is editable again.
    expect(textarea).toHaveValue('My prompt text');
    expect(textarea).toBeEnabled();
  });

  it('truthfully labels a draft that had no site evidence to ground it', async () => {
    mockBase();
    mswServer.use(
      http.post('/api/v1/content/generations', () =>
        HttpResponse.json(
          generation({
            status: 'succeeded',
            grounding_status: 'unavailable',
            grounding_summary: {
              version: 'content-context-v1',
              crawl_page_count: 0,
              crawl_urls: [],
              crawl_completed_at: null,
              brand_fields: [],
              search_connected: false,
              omissions: [],
            },
            output_text: 'Draft',
          }),
          { status: 202 },
        ),
      ),
    );
    renderScreen();
    await userEvent.type(
      await screen.findByRole('textbox', { name: /describe the website content/i }),
      'My prompt text',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Generate' }));
    expect(
      await screen.findByText(/grounded with: no site evidence available/i),
    ).toBeInTheDocument();
  });

  it('a failed generation offers Try again, which enqueues a new record', async () => {
    let retried = false;
    mockBase();
    mswServer.use(
      http.post('/api/v1/content/generations', () =>
        HttpResponse.json(generation(), { status: 201 }),
      ),
      http.get(`/api/v1/content/generations/${GEN}`, () =>
        HttpResponse.json(generation({ status: 'failed', error_code: 'auth_failure' })),
      ),
      http.post(`/api/v1/content/generations/${GEN}/try-again`, () => {
        retried = true;
        return HttpResponse.json(generation({ id: '55555555-5555-4555-8555-555555555555' }), {
          status: 201,
        });
      }),
      http.get('/api/v1/content/generations/55555555-5555-4555-8555-555555555555', () =>
        HttpResponse.json(generation({ id: '55555555-5555-4555-8555-555555555555' })),
      ),
    );
    renderScreen();
    await userEvent.type(
      await screen.findByRole('textbox', { name: /describe the website content/i }),
      'Page',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Generate' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/generation failed/i);
    await userEvent.click(screen.getByRole('button', { name: /try again/i }));
    await waitFor(() => expect(retried).toBe(true));
  });
});
