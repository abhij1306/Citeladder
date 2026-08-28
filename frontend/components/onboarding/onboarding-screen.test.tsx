import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

import type { BrandDiscovery } from '@/lib/api/brand-discoveries';
import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';

import { OnboardingScreen } from './onboarding-screen';

const { replace, setActiveProjectId } = vi.hoisted(() => ({
  replace: vi.fn(),
  setActiveProjectId: vi.fn(),
}));

const DISCOVERY_ID = '11111111-1111-4111-8111-111111111111';
const PROJECT_ID = '22222222-2222-4222-8222-222222222222';
const CRAWL_ID = '33333333-3333-4333-8333-333333333333';

let discoveryState: BrandDiscovery;
// The URL the screen loads with. A reload mid-generation resumes straight to
// the review step, which is the only way to reach that screen without a
// `ready` discovery to click through.
let searchParams = '';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace }),
  useSearchParams: () => new URLSearchParams(searchParams),
}));

vi.mock('@/lib/project/project-context', () => ({
  useProjectContext: () => ({ setActiveProjectId }),
}));

vi.mock('@/lib/onboarding/use-brand-discovery', () => ({
  // Mirrors the real hook: a persisted `resumeId` alone is enough to resolve
  // the discovery. On reload the brand draft is hydrated FROM that row, so
  // gating on `input` only would leave the screen with no discovery at all.
  useBrandDiscovery: (input: unknown, resumeId: string | null = null) => {
    const resolved = input || resumeId ? discoveryState : null;
    return {
      discovery: resolved,
      isRunning: Boolean(resolved) && ['queued', 'running'].includes(discoveryState.status),
      error: null,
      retry: vi.fn(),
    };
  },
}));

function discovery(status: BrandDiscovery['status'], phase: BrandDiscovery['progress']['phase']) {
  return {
    id: DISCOVERY_ID,
    workspace_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    project_id: null,
    status,
    progress: {
      phase,
      completed_steps: status === 'ready' ? 4 : 2,
      total_steps: 4,
      pages_read: 3,
      competitors_found: 1,
      prompts_prepared: 0,
    },
    input_data: {
      brand_name: 'Acme',
      website_url: 'https://acme.example',
      industry: 'Software',
      subindustry: 'Analytics',
      primary_market: 'US',
      language_code: 'en',
    },
    profile: {
      description: 'A commerce platform',
      positioning: 'Reliable product data',
      products_services: ['Product feeds'],
      target_audience: 'Retailers',
      industry: 'Commerce software',
      business_type: 'b2b',
      price_tier: 'premium',
      field_confidence: {},
      category: 'product feed management platform',
      category_options: [],
      category_aliases: ['feed management software'],
      category_terms: ['product feed management', 'marketplace integrations'],
      jobs_to_be_done: ['list products on marketplaces'],
      sector: 'Software',
      business_model: 'b2b_saas',
      secondary_business_models: [],
      market_scope: 'global',
      buyer_register: 'research_comparative',
      buyer_roles: ['ecommerce manager'],
      service_areas: [],
      knowledge_strength: 'strong',
    },
    domains: ['acme.example'],
    competitors: [
      {
        name: 'Globex',
        aliases: [],
        domains: ['globex.example'],
        qualification: null,
        reasoning: 'Serves the same analytics buyers in US.',
        evidence_urls: ['https://globex.example/'],
        confidence: 0.8,
      },
    ],
    topics: [
      {
        topic_id: '11111111-1111-4111-8111-111111111111',
        name: 'Product feeds',
        description: '',
        source_refs: ['page-1'],
      },
      {
        topic_id: '22222222-2222-4222-8222-222222222222',
        name: 'Catalog management',
        description: '',
        source_refs: ['page-1'],
      },
      {
        topic_id: '33333333-3333-4333-8333-333333333333',
        name: 'Marketplace syndication',
        description: '',
        source_refs: ['page-1'],
      },
    ],
    prompt_suggestions: [],
    evidence: [],
    warnings: [],
    gaps: [],
    error_code: '',
    created_at: '2026-08-04T00:00:00Z',
    updated_at: '2026-08-04T00:00:00Z',
  } satisfies BrandDiscovery;
}

function catalogHandler() {
  return http.get('/api/v1/brand-discovery-catalog', () =>
    HttpResponse.json({
      business_types: ['b2b', 'b2c', 'both'],
      price_tiers: ['premium'],
      required_fields: [],
      optional_fields: [],
      capture_methods: [],
      maximum_competitors: 5,
      industries: ['General', 'Software'],
      subindustries: { General: [], Software: ['Analytics'] },
      prompt_cohorts: ['core', 'brand_diagnostic'],
    }),
  );
}

async function enterBrand() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/^Brand name/), 'Acme');
  await user.type(screen.getByLabelText(/^Website/), 'acme.example');
  await user.click(screen.getByRole('button', { name: 'Continue' }));
  return user;
}

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  mswServer.resetHandlers();
  vi.clearAllMocks();
  searchParams = '';
});
afterAll(() => mswServer.close());

describe('OnboardingScreen', () => {
  it('renders persisted discovery facts in human language without raw diagnostics', async () => {
    discoveryState = discovery('running', 'finding_competitors');
    mswServer.use(catalogHandler());
    renderWithProviders(<OnboardingScreen />);

    await enterBrand();

    expect(screen.getByText('Opening your website')).toBeInTheDocument();
    expect(screen.getByText('Finding comparable brands')).toBeInTheDocument();
    expect(screen.getByText('3 useful pages read')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(
      /finding_competitors|lease|attempt_count|error_detail|provider/i,
    );
  });

  it('explains unavailable topic selection without a generic warning', async () => {
    discoveryState = {
      ...discovery('ready', 'preparing_review'),
      warnings: ['topic_selection_unavailable'],
    };
    mswServer.use(catalogHandler());
    renderWithProviders(<OnboardingScreen />);

    await enterBrand();

    expect(
      screen.getByText('Your starting topics will be created from the offerings you confirm.'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Some research could not be confirmed/i)).toBeNull();
  });

  it('submits one confirmed ICP completion and redirects to the command center', async () => {
    discoveryState = discovery('ready', 'preparing_review');
    let completionBody: unknown;
    mswServer.use(
      catalogHandler(),
      http.post(`/api/v1/brand-discoveries/${DISCOVERY_ID}/complete`, async ({ request }) => {
        completionBody = await request.json();
        // A completion whose project already exists (the replay path) carries
        // its id straight back, so the redirect needs no poll.
        return HttpResponse.json(
          {
            discovery_id: DISCOVERY_ID,
            status: 'project_created',
            project_id: PROJECT_ID,
            crawl_id: CRAWL_ID,
            activation_state: 'queued',
            page_limit: 10,
            warnings: [],
          },
          { status: 202 },
        );
      }),
      http.post(`/api/v1/projects/${PROJECT_ID}/logos/refresh`, () => HttpResponse.json({})),
    );
    renderWithProviders(<OnboardingScreen />);

    const user = await enterBrand();
    // The rail follows the step. A two-field form keeps a narrow measure; the
    // review step is a dense chip grid and gets the pane's full width, instead
    // of stacking into a tall ribbon with two-thirds of the screen unused.
    expect(screen.getByRole('main')).toHaveClass('max-w-xl');
    await user.click(screen.getByRole('button', { name: 'Review' }));
    expect(screen.getByRole('main')).toHaveClass('max-w-6xl');
    expect(screen.getByRole('main')).not.toHaveClass('max-w-xl');
    const createProject = await screen.findByRole('button', { name: 'Create project' });
    await waitFor(() => expect(createProject).toBeEnabled());
    await user.click(createProject);

    await waitFor(() => expect(completionBody).toBeDefined());
    expect(completionBody).toMatchObject({
      profile: {
        positioning: 'Reliable product data',
        products_services: ['Product feeds'],
        target_audience: 'Retailers',
      },
    });
    expect(JSON.stringify(completionBody)).not.toContain('prompt_groups');
    expect(setActiveProjectId).toHaveBeenCalledWith(PROJECT_ID);
    expect(replace).toHaveBeenCalledWith('/projects');
  });

  it('waits for the queued portfolio instead of reporting a failure', async () => {
    // Generation runs on a worker because it outlives a client request. The
    // accepted response carries no project id, so the screen must keep saying
    // "Creating…" and redirect only once the polled discovery lands the
    // project -- not fall through to "we couldn't finish this setup step".
    discoveryState = discovery('ready', 'preparing_review');
    mswServer.use(
      catalogHandler(),
      http.post(`/api/v1/brand-discoveries/${DISCOVERY_ID}/complete`, () =>
        HttpResponse.json(
          {
            discovery_id: DISCOVERY_ID,
            status: 'completing',
            project_id: null,
            crawl_id: null,
            activation_state: 'queued',
            page_limit: null,
            warnings: [],
          },
          { status: 202 },
        ),
      ),
      http.post(`/api/v1/projects/${PROJECT_ID}/logos/refresh`, () => HttpResponse.json({})),
    );
    const view = renderWithProviders(<OnboardingScreen />);

    const user = await enterBrand();
    await user.click(screen.getByRole('button', { name: 'Review' }));
    const createProject = await screen.findByRole('button', { name: 'Create project' });
    await waitFor(() => expect(createProject).toBeEnabled());
    await user.click(createProject);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Creating…' })).toBeDisabled());
    expect(screen.queryByText(/couldn’t finish this setup step/i)).not.toBeInTheDocument();
    // `replace` also carries the step into the URL, so assert the destination.
    expect(replace).not.toHaveBeenCalledWith('/projects');

    // The worker lands the project; the discovery poll is what tells the UI.
    discoveryState = {
      ...discovery('project_created', 'complete'),
      project_id: PROJECT_ID,
    };
    view.rerender(<OnboardingScreen />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/projects'));
    expect(setActiveProjectId).toHaveBeenCalledWith(PROJECT_ID);
  });

  it('keeps creation disabled after a reload while the worker is still going', async () => {
    // On reload the mutation is fresh -- not pending, not successful -- so the
    // polled status is the only thing that knows a job is already running.
    // Without it the button re-enabled and invited the second click this whole
    // change exists to remove.
    searchParams = `discovery=${DISCOVERY_ID}&step=review`;
    discoveryState = discovery('completing', 'preparing_review');
    mswServer.use(catalogHandler());
    renderWithProviders(<OnboardingScreen />);

    const creating = await screen.findByRole('button', { name: 'Creating…' });
    expect(creating).toBeDisabled();
  });

  it('reports a queued generation failure without replaying the failed job', async () => {
    searchParams = `discovery=${DISCOVERY_ID}&step=review`;
    discoveryState = discovery('failed', 'preparing_review');
    mswServer.use(catalogHandler());
    renderWithProviders(<OnboardingScreen />);

    expect(await screen.findByText(/project creation did not finish/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create project' })).toBeDisabled();
  });

  it('gates creation on the one thing the confirm screen asks for', async () => {
    // Brand knowledge moved to the app, so a blank category -- not a blank
    // positioning statement -- is what should block project creation.
    const ready = discovery('ready', 'preparing_review');
    discoveryState = {
      ...ready,
      profile: { ...ready.profile, category: '', category_options: [], category_aliases: [] },
    };
    mswServer.use(catalogHandler());
    renderWithProviders(<OnboardingScreen />);

    const user = await enterBrand();
    await user.click(screen.getByRole('button', { name: 'Review' }));
    const createProject = await screen.findByRole('button', { name: 'Create project' });
    expect(createProject).toBeDisabled();

    await user.click(screen.getByRole('radio', { name: 'Other' }));
    await user.type(screen.getByLabelText(/describe what you sell/i), 'mattress brand');
    expect(createProject).toBeEnabled();
  });

  it('never asks the user to write brand prose', async () => {
    mswServer.use(catalogHandler());
    renderWithProviders(<OnboardingScreen />);

    const user = await enterBrand();
    await user.click(screen.getByRole('button', { name: 'Review' }));
    await screen.findByRole('button', { name: 'Create project' });

    expect(screen.queryByLabelText(/positioning/i)).toBeNull();
    expect(screen.queryByLabelText(/target audience/i)).toBeNull();
    expect(screen.queryByLabelText(/^description/i)).toBeNull();
  });

  it('selects only the first five discovered competitors', async () => {
    discoveryState = {
      ...discovery('ready', 'preparing_review'),
      competitors: Array.from({ length: 6 }, (_, index) => ({
        name: `Peer ${index + 1}`,
        aliases: [],
        domains: [`peer-${index + 1}.example`],
        qualification: null,
        reasoning: '',
        evidence_urls: [],
        confidence: 0,
      })),
    };
    mswServer.use(catalogHandler());
    renderWithProviders(<OnboardingScreen />);

    const user = await enterBrand();
    await user.click(screen.getByRole('button', { name: 'Review' }));

    expect(await screen.findByText('5 of 5 tracked')).toBeInTheDocument();
    // The chip keeps its own name in both states; `aria-pressed` carries
    // whether it is tracked.
    expect(screen.getByRole('button', { name: 'Peer 6' })).toHaveAttribute('aria-pressed', 'false');
  });
});
