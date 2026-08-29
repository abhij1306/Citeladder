import { http, HttpResponse } from 'msw';
import type { z } from 'zod';
import { afterAll, afterEach, beforeAll, beforeEach, vi } from 'vitest';

import { auditSchema } from '@/lib/api/schemas/audits';
import { projectSchema } from '@/lib/api/schemas/project';
import { visibilitySchema } from '@/lib/api/schemas/visibility';
import {
  visibilityEvidenceResponseSchema,
  visibilityExecutionEvidenceSchema,
} from '@/lib/api/schemas/visibility-evidence';
import { visibilityTrendPointSchema } from '@/lib/api/schemas/visibility-trends';
import { setActiveWorkspaceId } from '@/lib/api/client';
import { ProjectProvider } from '@/lib/project/project-context';
import VisibilityPage from '@/app/(app)/visibility/page';
import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';

type Audit = z.infer<typeof auditSchema>;
type Project = z.infer<typeof projectSchema>;
type Visibility = z.infer<typeof visibilitySchema>;
type VisibilityEvidenceResponse = z.infer<typeof visibilityEvidenceResponseSchema>;
type VisibilityExecutionEvidence = z.infer<typeof visibilityExecutionEvidenceSchema>;
type VisibilityTrendPoint = z.infer<typeof visibilityTrendPointSchema>;

const WORKSPACE_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
export const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
export const AUDIT_LATEST = '22222222-2222-4222-8222-222222222222';
export const AUDIT_OLDER = '33333333-3333-4333-8333-333333333333';
const ANALYSIS_A = '44444444-4444-4444-8444-444444444444';
export const ANALYSIS_B = '55555555-5555-4555-8555-555555555555';
export const ANALYSIS_C = '66666666-6666-4666-8666-666666666666';
const PROMPT_A = '77777777-7777-4777-8777-777777777777';
const SNAP_A = '88888888-8888-4888-8888-888888888888';

export function makeProject(): Project {
  return {
    id: PROJECT_ID,
    workspace_id: WORKSPACE_ID,
    name: 'CiteLadder',
    brand_name: 'Acme',
    website_url: 'https://acme.com',
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
    prompt_sets: [],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

export function makeAudit(id: string, completedAt: string): Audit {
  return {
    id,
    workspace_id: WORKSPACE_ID,
    project_id: PROJECT_ID,
    status: 'completed',
    benchmark_mode: 'consumer_like',
    audit_scope: 'brand',
    model_provenance: [],
    repetitions: 2,
    random_seed: '1',
    requested_count: 6,
    completed_count: 6,
    failed_count: 0,
    error_message: '',
    engine_snapshots: [],
    created_at: completedAt,
    updated_at: completedAt,
    started_at: completedAt,
    completed_at: completedAt,
  };
}

export function makeVisibility(auditId: string, score: number): Visibility {
  return {
    project_id: PROJECT_ID,
    audit_id: auditId,
    audit_status: 'completed',
    analyzer_version: 'v1',
    scoring_rule_version: 'v1',
    cohort: 'core',
    coverage: {},
    total_completed: 6,
    total_failed: 0,
    visibility_score: score,
    model_provenance: [],
    rankings: [
      {
        name: 'Acme',
        is_brand: true,
        mention_rate: score / 100,
        citation_rate: 0.3,
        share_of_voice: 0.6,
        mention_count: 4,
        sentiment: null,
        avg_position: null,
      },
      {
        name: 'Globex',
        is_brand: false,
        mention_rate: 0.3,
        citation_rate: 0.1,
        share_of_voice: 0.4,
        mention_count: 2,
        sentiment: null,
        avg_position: null,
      },
    ],
    per_engine: [
      {
        logical_engine: 'gemini',
        total_completed: 3,
        brand_mention_rate: 0.6,
        owned_citation_rate: 0.3,
        search_use_rate: 0.5,
        visibility_score: 60,
      },
      {
        logical_engine: 'claude',
        total_completed: 3,
        brand_mention_rate: 0.7,
        owned_citation_rate: 0.4,
        search_use_rate: 0.6,
        visibility_score: 70,
      },
    ],
    sentiment: null,
    avg_position: null,
    created_at: '2026-07-15T00:00:00Z',
  };
}

export function makeTrendPoint(
  auditId: string,
  completedAt: string,
  score: number | null,
): VisibilityTrendPoint {
  return {
    audit_id: auditId,
    completed_at: completedAt,
    logical_engine: null,
    visibility_score: score,
    brand_mention_rate: 0.5,
    owned_citation_rate: 0.3,
    sov: { response: 0.4, mention: 0.5 },
    rankings: [
      {
        name: 'Acme',
        is_brand: true,
        website_url: 'https://acme.com',
        mention_rate: 0.5,
        citation_rate: 0.3,
        share_of_voice: 0.6,
        mention_count: 4,
        sentiment: null,
        avg_position: null,
      },
    ],
    sentiment: null,
    avg_position: null,
    transport_model: null,
    retrieval_enabled: null,
    model_provenance: [],
    source_snapshot_ids: [],
    analyzer_versions: ['v1'],
    scoring_rule_versions: ['v1'],
    spans_version_boundary: false,
  };
}

function makeCitation(ordinal: number) {
  return {
    ordinal,
    url: 'https://acme.com/blog',
    title: 'Acme Blog',
    domain: 'acme.com',
    classification: 'owned' as const,
    is_owned: true,
    is_unintended: false,
    matched_competitor: null,
  };
}

export function makeEvidenceItem(
  overrides: Partial<VisibilityExecutionEvidence> = {},
): VisibilityExecutionEvidence {
  return {
    audit_id: AUDIT_LATEST,
    task_id: '99999999-9999-4999-8999-999999999999',
    analysis_id: ANALYSIS_A,
    artifact_id: 'abababab-abab-4bab-8bab-abababababab',
    prompt_snapshot_id: SNAP_A,
    prompt_id: PROMPT_A,
    prompt_index: 3,
    prompt_text: 'Best affordable clothing stores in Australia?',
    repetition: 1,
    completed_at: '2026-07-15T14:32:00Z',
    logical_engine: 'chatgpt',
    transport_provider: 'openai',
    transport_model: 'gpt-5.4',
    retrieval_enabled: null,
    search_used: true,
    search_query_count: 2,
    query_text_available: true,
    state: 'queries_available',
    search_events: [
      {
        sequence: 0,
        query: 'affordable family clothing Australia 2026',
        call_id: 'c1',
        call_sequence: 0,
        query_sequence: 0,
      },
      {
        sequence: 1,
        query: 'best budget clothing shops families',
        call_id: 'c1',
        call_sequence: 0,
        query_sequence: 1,
      },
    ],
    event_source: 'raw_artifact',
    mentions: [
      { kind: 'brand', name: 'Acme', first_offset: 12, artifact_id: null, analyzer_version: 'v1' },
      {
        kind: 'competitor',
        name: 'Globex',
        first_offset: null,
        artifact_id: null,
        analyzer_version: 'v1',
      },
    ],
    citations: [makeCitation(1)],
    ...overrides,
  };
}

export function makeEvidenceResponse(
  overrides: Partial<VisibilityEvidenceResponse> = {},
): VisibilityEvidenceResponse {
  return { items: [makeEvidenceItem()], truncated: false, ...overrides };
}

export function renderVisibilityPage() {
  return renderWithProviders(
    <ProjectProvider>
      <VisibilityPage />
    </ProjectProvider>,
  );
}

/** Register the project + audits handlers shared by most tests. */
export function useBaseVisibilityHandlers(extra: Parameters<typeof mswServer.use> = []) {
  mswServer.use(
    ...extra,
    http.get('/api/v1/projects', () => HttpResponse.json([makeProject()])),
    http.post(`/api/v1/projects/${PROJECT_ID}/logos/refresh`, () => HttpResponse.json({})),
    http.get('/api/v1/audits', () =>
      HttpResponse.json([makeAudit(AUDIT_LATEST, '2026-07-15T00:00:00Z')]),
    ),
    http.get(`/api/v1/projects/${PROJECT_ID}/visibility`, () =>
      HttpResponse.json(makeVisibility(AUDIT_LATEST, 67)),
    ),
    http.get(`/api/v1/projects/${PROJECT_ID}/visibility/trends`, () =>
      HttpResponse.json([
        makeTrendPoint(AUDIT_OLDER, '2026-07-10T00:00:00Z', 55),
        makeTrendPoint(AUDIT_LATEST, '2026-07-15T00:00:00Z', 67),
      ]),
    ),
    http.get(`/api/v1/projects/${PROJECT_ID}/visibility/prompts`, () => HttpResponse.json([])),
  );
}

export function setupVisibilityPageTests(resetNavigation: () => void) {
  beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
  beforeEach(() => {
    window.localStorage?.clear();
    setActiveWorkspaceId(null);
    resetNavigation();
  });
  afterEach(() => {
    mswServer.resetHandlers();
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });
  afterAll(() => mswServer.close());
}
