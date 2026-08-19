import { http, HttpResponse } from 'msw';
import type { z } from 'zod';
import { afterAll, afterEach, beforeAll, beforeEach, vi } from 'vitest';

import {
  projectSchema,
  promptSchema,
  promptSetSchema,
  topicSchema,
} from '@/lib/api/schemas/project';
import { visibilityExecutionEvidenceSchema } from '@/lib/api/schemas/visibility-evidence';
import { setActiveWorkspaceId } from '@/lib/api/client';
import { ProjectProvider } from '@/lib/project/project-context';
import PromptsPage from '@/app/(app)/prompts/page';
import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';

type Project = z.infer<typeof projectSchema>;
type Prompt = z.infer<typeof promptSchema>;
type PromptSet = z.infer<typeof promptSetSchema>;
type Topic = z.infer<typeof topicSchema>;
type VisibilityExecutionEvidence = z.infer<typeof visibilityExecutionEvidenceSchema>;

export const WORKSPACE_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
export const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
export const SET_ID = '22222222-2222-4222-8222-222222222222';
export const TOPIC_ID = '55555555-5555-4555-8555-555555555555';

export function makePrompt(overrides: Partial<Prompt> = {}): Prompt {
  return {
    id: '33333333-3333-4333-8333-333333333333',
    prompt_set_id: SET_ID,
    text: 'Best running shoes?',
    theme: 'Comfort',
    intent: 'discovery',
    cohort: 'core',
    branded: false,
    enabled: true,
    status: 'active',
    origin: 'manual',
    ...overrides,
  };
}

export function makeTopic(overrides: Partial<Topic> = {}): Topic {
  return {
    id: TOPIC_ID,
    project_id: PROJECT_ID,
    name: 'Footwear',
    description: '',
    origin: 'manual',
    active_count: 1,
    proposed_count: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

export function makeEvidenceItem(
  promptId: string,
  brandMentioned: boolean,
  taskId: string,
): VisibilityExecutionEvidence {
  return {
    audit_id: '99999999-9999-4999-8999-999999999999',
    task_id: taskId,
    analysis_id: taskId,
    artifact_id: null,
    prompt_snapshot_id: taskId,
    prompt_id: promptId,
    prompt_index: 0,
    prompt_text: 'Best running shoes?',
    repetition: 1,
    completed_at: '2026-01-02T00:00:00Z',
    logical_engine: 'chatgpt',
    transport_provider: 'openai',
    transport_model: 'gpt-test',
    measurement_mode: '',
    retrieval_enabled: null,
    search_used: false,
    search_query_count: 0,
    query_text_available: false,
    state: 'count_only',
    search_events: [],
    event_source: 'none',
    mentions: brandMentioned
      ? [
          {
            kind: 'brand',
            name: 'CiteLadder',
            first_offset: 0,
            artifact_id: null,
            analyzer_version: 'v1',
          },
        ]
      : [],
    citations: [],
  };
}

export function makeSet(prompts: Prompt[]): PromptSet {
  return {
    id: SET_ID,
    project_id: PROJECT_ID,
    name: 'Default prompt set',
    description: '',
    prompt_count: prompts.length,
    prompts,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

export function makeProject(promptSets: PromptSet[]): Project {
  return {
    id: PROJECT_ID,
    workspace_id: WORKSPACE_ID,
    name: 'CiteLadder',
    brand_name: 'CiteLadder',
    website_url: 'https://citeladder.com',
    industry: 'General',
    subindustry: '',
    primary_market: 'US',
    country_code: 'US',
    language_code: 'en',
    benchmark_mode: 'consumer_like',
    default_repetitions: 3,
    brand: { aliases: [] },
    owned_domains: [],
    unintended_domains: [],
    competitors: [],
    prompt_sets: promptSets,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

export function usePromptPageHandlers(
  prompts: Prompt[],
  topics: Topic[] = [],
  evidenceItems: VisibilityExecutionEvidence[] = [],
): PromptSet {
  const set = makeSet(prompts);
  mswServer.use(
    http.get('/api/v1/projects', () => HttpResponse.json([makeProject([set])])),
    http.post(`/api/v1/projects/${PROJECT_ID}/logos/refresh`, () =>
      HttpResponse.json(makeProject([set])),
    ),
    http.get('/api/v1/prompt-sets', () => HttpResponse.json([set])),
    http.get(`/api/v1/projects/${PROJECT_ID}/topics`, () => HttpResponse.json(topics)),
    http.get(`/api/v1/projects/${PROJECT_ID}/visibility/evidence`, () =>
      HttpResponse.json({ items: evidenceItems, truncated: false }),
    ),
  );
  return set;
}

export function renderPromptsPage() {
  return renderWithProviders(
    <ProjectProvider>
      <PromptsPage />
    </ProjectProvider>,
  );
}

export function setupPromptsPageTests(resetNavigation: () => void) {
  beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
  beforeEach(() => {
    window.localStorage.clear();
    setActiveWorkspaceId(null);
    resetNavigation();
  });
  afterEach(() => {
    mswServer.resetHandlers();
    vi.restoreAllMocks();
  });
  afterAll(() => mswServer.close());
}
