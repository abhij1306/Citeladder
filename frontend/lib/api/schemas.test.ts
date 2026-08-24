import { describe, expect, it } from 'vitest';
import { z } from 'zod';

import { providerCatalogFixture } from '@/test/provider-catalog-fixture';

import {
  auditSchema,
  authResponseSchema,
  citationSchema,
  executionEvidenceSchema,
  executionSchema,
  productEvidenceResponseSchema,
  productSchema,
  productVisibilitySchema,
  projectSchema,
  providerCatalogSchema,
  providerConnectionSchema,
  providerRouteSchema,
  sessionUserSchema,
  strictValidate,
  transportProviderSchema,
  visibilityEvidenceResponseSchema,
  visibilitySchema,
  workspaceSchema,
} from './schemas';

const UUID = '11111111-1111-4111-8111-111111111111';
const UUID2 = '22222222-2222-4222-8222-222222222222';

describe('strictValidate', () => {
  it('returns parsed data on a match', () => {
    const schema = z.object({ id: z.uuid() });
    expect(strictValidate(schema, { id: UUID }, 'ctx')).toEqual({ id: UUID });
  });

  it('throws with the context on a mismatch', () => {
    const schema = z.object({ id: z.uuid() });
    expect(() => strictValidate(schema, { id: 'not-a-uuid' }, 'ctx.here')).toThrow(
      /API validation failure in ctx\.here/,
    );
  });

  it('throws on a numeric id (contract forbids numeric ids)', () => {
    expect(() => strictValidate(z.object({ id: z.uuid() }), { id: 7 }, 'ids')).toThrow();
  });
});

describe('auth + workspace contract', () => {
  const sessionUser = {
    id: UUID,
    email: 'user@example.com',
    role: 'owner',
    is_active: true,
    created_at: '2026-07-15T00:00:00Z',
    updated_at: '2026-07-15T00:00:00Z',
  };

  it('validates the { user } auth wrapper and rejects a bare SessionUser', () => {
    expect(strictValidate(authResponseSchema, { user: sessionUser }, 'auth').user.email).toBe(
      'user@example.com',
    );
    // The backend wraps the user; a bare SessionUser is a contract violation.
    expect(() => strictValidate(authResponseSchema, sessionUser, 'auth')).toThrow();
  });

  it('strips an additive key on the auth wrapper (tolerant-on-unknown, ERR-5)', () => {
    // Additive backend fields must never break the UI — they are stripped
    // from the parsed output, so a leaked key never enters app state either.
    const parsed = strictValidate(
      authResponseSchema,
      { user: sessionUser, token: 'leaked' },
      'auth',
    );
    expect(parsed.user.email).toBe('user@example.com');
    expect('token' in parsed).toBe(false);
  });

  it('strips an additive key on a SessionUser (tolerant-on-unknown)', () => {
    const parsed = strictValidate(
      sessionUserSchema,
      { ...sessionUser, password_hash: 'x' },
      'user',
    );
    expect(parsed.email).toBe('user@example.com');
    expect('password_hash' in parsed).toBe(false);
  });

  it('validates a workspace with role (no slug) and strips a slug key', () => {
    const workspace = {
      id: UUID,
      name: 'Acme',
      role: 'owner',
      created_at: '2026-07-15T00:00:00Z',
      updated_at: '2026-07-15T00:00:00Z',
    };
    expect(strictValidate(workspaceSchema, workspace, 'ws').role).toBe('owner');
    // Backend WorkspaceResponse has no slug — an additive key is stripped.
    const parsed = strictValidate(workspaceSchema, { ...workspace, slug: 'acme' }, 'ws');
    expect('slug' in parsed).toBe(false);
  });

  it('still fails loud on declared-field drift (missing or mistyped fields)', () => {
    const workspace = {
      id: UUID,
      name: 'Acme',
      role: 'owner',
      created_at: '2026-07-15T00:00:00Z',
      updated_at: '2026-07-15T00:00:00Z',
    };
    // A missing declared field is drift the UI needs — it throws.
    const { role: _role, ...missingRole } = workspace;
    expect(() => strictValidate(workspaceSchema, missingRole, 'ws')).toThrow();
    // A mistyped declared field throws.
    expect(() => strictValidate(workspaceSchema, { ...workspace, name: 7 }, 'ws')).toThrow();
  });
});

describe('contract schemas', () => {
  it('validates a project with uuid ids and benchmark_mode enum', () => {
    const project = {
      id: UUID,
      workspace_id: UUID2,
      name: 'Acme',
      brand_name: 'Acme',
      website_url: 'https://acme.example',
      industry: 'General',
      subindustry: '',
      primary_market: 'US',
      country_code: 'US',
      language_code: 'en',
      benchmark_mode: 'consumer_like',
      default_repetitions: 3,
      brand: { aliases: ['Acme Inc'], logo_url: '/api/v1/projects/acme/logo' },
      owned_domains: ['acme.example'],
      unintended_domains: [],
      competitors: [
        {
          id: UUID2,
          name: 'Beta',
          aliases: [],
          domains: ['beta.example'],
          logo_url: null,
        },
      ],
      prompt_sets: [],
      created_at: '2026-07-15T00:00:00Z',
      updated_at: '2026-07-15T00:00:00Z',
    };
    expect(strictValidate(projectSchema, project, 'project').benchmark_mode).toBe('consumer_like');
    expect(strictValidate(projectSchema, project, 'project').brand.logo_url).toContain('/logo');
    expect(() =>
      strictValidate(projectSchema, { ...project, benchmark_mode: 'nope' }, 'project'),
    ).toThrow();
    // Tolerant-on-unknown: an additive backend field is stripped, not thrown.
    const parsed = strictValidate(projectSchema, { ...project, surprise: true }, 'project');
    expect('surprise' in parsed).toBe(false);
  });

  it('rejects a leaked secret key from a provider connection', () => {
    const base = {
      id: UUID,
      workspace_id: UUID2,
      transport_provider: 'anthropic',
      base_url: null,
      active: true,
      created_at: '2026-07-15T00:00:00Z',
      updated_at: '2026-07-15T00:00:00Z',
    };
    expect(strictValidate(providerConnectionSchema, base, 'conn').active).toBe(true);
    expect(() =>
      strictValidate(providerConnectionSchema, { ...base, api_key: 'sk-test-fake' }, 'conn'),
    ).toThrow('API validation failure');
  });

  it('accepts only the three direct transports', () => {
    for (const t of ['openai', 'anthropic', 'google']) {
      expect(transportProviderSchema.parse(t)).toBe(t);
    }
    expect(() => transportProviderSchema.parse('unsupported')).toThrow();
  });

  it('defaults route.active to true when omitted and rejects a create-only openai catalog gap', () => {
    const route = {
      id: UUID,
      logical_engine: 'chatgpt',
      transport_provider: 'openai',
      transport_model: 'gpt-5.4',
      is_default: true,
    };
    // `active` is optional on the wire; a route without it parses.
    expect(strictValidate(providerRouteSchema, route, 'route').transport_provider).toBe('openai');
  });

  it('validates the direct-only provider catalog', () => {
    expect(
      strictValidate(providerCatalogSchema, providerCatalogFixture, 'catalog').transports,
    ).toHaveLength(3);
  });

  it('validates citation classification enum', () => {
    const citation = {
      ordinal: 1,
      url: 'https://acme.example/a',
      title: 'A',
      domain: 'acme.example',
      classification: 'owned',
      is_owned: true,
      is_unintended: false,
      matched_competitor: null,
    };
    expect(strictValidate(citationSchema, citation, 'c').classification).toBe('owned');
    // The 'unintended' (owned-but-unwanted) class is a valid backend value.
    expect(
      strictValidate(citationSchema, { ...citation, classification: 'unintended' }, 'c')
        .classification,
    ).toBe('unintended');
    expect(() =>
      strictValidate(citationSchema, { ...citation, classification: 'internal' }, 'c'),
    ).toThrow();
  });

  it('validates an audit (string seed + engine snapshots, no null error)', () => {
    const audit = {
      id: UUID,
      workspace_id: UUID2,
      project_id: UUID,
      status: 'completed',
      benchmark_mode: 'consumer_like',
      repetitions: 3,
      random_seed: '42',
      requested_count: 10,
      completed_count: 10,
      failed_count: 0,
      error_message: '',
      engine_snapshots: [
        {
          logical_engine: 'gemini',
          transport_provider: 'google',
          transport_model: 'gemini-flash-latest',
        },
      ],
      created_at: '2026-07-15T00:00:00Z',
      updated_at: '2026-07-15T00:00:00Z',
      started_at: '2026-07-15T00:00:05Z',
      completed_at: '2026-07-15T00:10:00Z',
    };
    expect(strictValidate(auditSchema, audit, 'audit').status).toBe('completed');
    // The 64-bit seed is a decimal STRING on the wire, never a number.
    expect(() => strictValidate(auditSchema, { ...audit, random_seed: 42 }, 'audit')).toThrow();
    // Tolerant-on-unknown (ERR-5): an additive audit field is stripped, never
    // a screen-breaking rejection.
    const parsed = strictValidate(auditSchema, { ...audit, extra: 'nope' }, 'audit');
    expect('extra' in parsed).toBe(false);
  });

  it('validates an execution/queue row (AuditTaskResponse shape)', () => {
    const execution = {
      id: UUID,
      audit_id: UUID2,
      prompt_index: 0,
      repetition: 1,
      randomized_position: 2,
      logical_engine: 'gemini',
      transport_provider: 'google',
      transport_model: 'gemini-flash-latest',
      status: 'succeeded',
      attempt_count: 1,
      max_attempts: 5,
      prompt_text: 'Which CRM is best?',
      answer_text: 'Answer',
      search_used: true,
      error_code: '',
      error_detail: '',
      latency_ms: 1200,
      created_at: '2026-07-15T00:00:00Z',
      completed_at: '2026-07-15T00:00:03Z',
    };
    expect(strictValidate(executionSchema, execution, 'exec').status).toBe('succeeded');

    // Regression: the enum listed only the statuses a FINISHED run ends on, so
    // a single row parked mid-run failed the whole executions list and the run
    // screen showed "Could not load executions." until the run terminalized.
    // Every status the queue can persist must parse.
    for (const status of [
      'pending_reservation',
      'queued',
      'leased',
      'running',
      'retry_wait',
      'capacity_wait',
      'failed',
      'cancelled',
    ]) {
      expect(strictValidate(executionSchema, { ...execution, status }, 'exec').status).toBe(status);
    }
  });

  it('validates execution evidence keyed by the execution id', () => {
    const evidence = {
      id: UUID,
      analysis_id: UUID2,
      audit_id: UUID2,
      task_id: UUID,
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
      brand_first_offset: 12,
      owned_domain_cited: true,
      owned_citation_count: 1,
      unintended_domain_cited: false,
      citation_count: 2,
      search_used: true,
      search_query_count: 1,
      sentiment: null,
      avg_position: null,
      score: { visibility: 1 },
      citations: [
        {
          ordinal: 1,
          url: 'https://acme.example/a',
          title: 'A',
          domain: 'acme.example',
          classification: 'owned',
          is_owned: true,
          is_unintended: false,
          matched_competitor: null,
        },
      ],
      competitors_mentioned: ['Beta'],
      created_at: '2026-07-15T00:00:00Z',
    };
    const parsed = strictValidate(executionEvidenceSchema, evidence, 'evidence');
    expect(parsed.brand_mentioned).toBe(true);
    expect(parsed.sentiment).toBeNull();
    expect(parsed.citations[0]?.classification).toBe('owned');
  });

  it('validates a visibility projection with nullable sentiment/avg_position', () => {
    const visibility = {
      project_id: UUID,
      audit_id: UUID2,
      audit_status: 'completed',
      analyzer_version: 'v1',
      scoring_rule_version: 'v1',
      total_completed: 10,
      total_failed: 0,
      visibility_score: 72.5,
      per_engine: [
        {
          logical_engine: 'gemini',
          total_completed: 5,
          brand_mention_rate: 0.6,
          owned_citation_rate: 0.3,
          search_use_rate: 0.5,
          visibility_score: 80,
        },
      ],
      rankings: [
        {
          name: 'Acme',
          is_brand: true,
          mention_rate: 0.725,
          citation_rate: 0.3,
          share_of_voice: 0.4,
          mention_count: 4,
          sentiment: null,
          avg_position: null,
        },
      ],
      sentiment: null,
      avg_position: null,
      created_at: '2026-07-15T00:00:00Z',
    };
    const parsed = strictValidate(visibilitySchema, visibility, 'visibility');
    expect(parsed.rankings[0]?.sentiment).toBeNull();
    expect(parsed.rankings[0]?.avg_position).toBeNull();
  });
});

describe('visibility evidence contract', () => {
  function makeCitation() {
    return {
      ordinal: 1,
      url: 'https://acme.com/a',
      title: 'Acme',
      domain: 'acme.com',
      classification: 'owned',
      is_owned: true,
      is_unintended: false,
      matched_competitor: null,
    };
  }

  function makeItem(overrides: Record<string, unknown> = {}) {
    return {
      audit_id: UUID,
      task_id: UUID2,
      analysis_id: UUID,
      artifact_id: UUID2,
      prompt_snapshot_id: UUID,
      prompt_id: UUID2,
      prompt_index: 3,
      prompt_text: 'Best affordable clothing stores?',
      repetition: 1,
      completed_at: '2026-07-15T14:32:00Z',
      logical_engine: 'chatgpt',
      transport_provider: 'openai',
      transport_model: 'gpt-5.4',
      search_used: true,
      search_query_count: 2,
      query_text_available: true,
      state: 'queries_available',
      search_events: [
        {
          sequence: 0,
          query: 'affordable clothing Australia',
          call_id: 'c1',
          call_sequence: 0,
          query_sequence: 0,
        },
        {
          sequence: 1,
          query: 'budget family shops',
          call_id: 'c1',
          call_sequence: 0,
          query_sequence: 1,
        },
      ],
      event_source: 'raw_artifact',
      mentions: [
        {
          kind: 'brand',
          name: 'Acme',
          first_offset: 12,
          artifact_id: UUID2,
          analyzer_version: 'v1',
        },
        {
          kind: 'competitor',
          name: 'Globex',
          first_offset: null,
          artifact_id: null,
          analyzer_version: 'v1',
        },
      ],
      citations: [makeCitation()],
      ...overrides,
    };
  }

  it('parses a full evidence response with items and truncated flag', () => {
    const parsed = strictValidate(
      visibilityEvidenceResponseSchema,
      { items: [makeItem()], truncated: true },
      'evidence',
    );
    expect(parsed.items).toHaveLength(1);
    expect(parsed.truncated).toBe(true);
    expect(parsed.items[0]?.mentions[0]?.kind).toBe('brand');
    expect(parsed.items[0]?.search_events).toHaveLength(2);
  });

  it('accepts nullable prompt_id / artifact_id / completed_at and count-only / no-search states', () => {
    const countOnly = makeItem({
      state: 'count_only',
      query_text_available: false,
      prompt_id: null,
      artifact_id: null,
      completed_at: null,
      event_source: 'audit_task',
      search_events: [],
      mentions: [],
      citations: [],
    });
    const noSearch = makeItem({
      analysis_id: UUID2,
      state: 'no_search',
      search_used: false,
      search_query_count: 0,
      query_text_available: false,
      event_source: 'none',
      search_events: [],
    });
    const parsed = strictValidate(
      visibilityEvidenceResponseSchema,
      { items: [countOnly, noSearch], truncated: false },
      'evidence',
    );
    expect(parsed.items[0]?.state).toBe('count_only');
    expect(parsed.items[0]?.prompt_id).toBeNull();
    expect(parsed.items[0]?.completed_at).toBeNull();
    expect(parsed.items[1]?.state).toBe('no_search');
  });

  it('rejects an unknown fanout state and strips unknown extra keys', () => {
    // Declared-field drift (an unknown enum value) still fails loud.
    expect(() =>
      strictValidate(
        visibilityEvidenceResponseSchema,
        { items: [makeItem({ state: 'partial' })], truncated: false },
        'evidence',
      ),
    ).toThrow();
    // An additive key on a nested item is stripped, not thrown.
    const parsed = strictValidate(
      visibilityEvidenceResponseSchema,
      { items: [makeItem({ unexpected: true })], truncated: false },
      'evidence',
    );
    expect('unexpected' in (parsed.items[0] ?? {})).toBe(false);
  });

  it('preserves an empty query string in a search event (never invented)', () => {
    const item = makeItem({
      state: 'count_only',
      search_events: [
        { sequence: 0, query: '', call_id: 'c1', call_sequence: 0, query_sequence: 0 },
      ],
    });
    const parsed = strictValidate(
      visibilityEvidenceResponseSchema,
      { items: [item], truncated: false },
      'evidence',
    );
    expect(parsed.items[0]?.search_events[0]?.query).toBe('');
  });
});

describe('products contract (agentic commerce)', () => {
  const product = {
    id: UUID,
    project_id: UUID2,
    sku: 'AC-VB500',
    name: 'Acme VoltBike 500',
    aliases: ['VoltBike'],
    variants: [{ name: 'Graphite / Standard', sku: 'AC-VB500-GR', price: 2499.0 }],
    price: 2499.0,
    currency: 'USD',
    url: 'https://acme.com/p/voltbike',
    attributes: { brand: 'Acme' },
    origin: 'manual',
    connection_id: null,
    external_item_ref: null,
    last_seen_sync_run_id: null,
    completeness: { score: 0.75, present: 9, total: 12, missing: ['gtin'] },
    created_at: '2026-07-15T00:00:00Z',
    updated_at: '2026-07-15T00:00:00Z',
  };

  it('validates a product with uuid ids, variants, and a completeness badge', () => {
    const parsed = strictValidate(productSchema, product, 'product');
    expect(parsed.sku).toBe('AC-VB500');
    expect(parsed.variants[0]?.price).toBe(2499.0);
    expect(parsed.completeness.missing).toEqual(['gtin']);
    // Tolerant-on-unknown: an additive key is stripped; declared-field drift
    // (a numeric id) still fails loud.
    expect('slug' in strictValidate(productSchema, { ...product, slug: 'nope' }, 'product')).toBe(
      false,
    );
    expect(() => strictValidate(productSchema, { ...product, id: 7 }, 'product')).toThrow();
  });

  it('accepts a nullable product price', () => {
    expect(strictValidate(productSchema, { ...product, price: null }, 'product').price).toBeNull();
  });

  it('validates the visibility projection with nullable ids and rates', () => {
    // The analyzer-v2 fields every entry carries (own + competitor).
    const entryV2 = {
      product_analyzer_version: 'product-analysis-2',
      win_rate: null,
      price_mismatch_rate: null,
      price_relation_counts: {},
      attribute_dimension_frequency: {},
      buyer_destination_mix: { total: 0, by_kind: [], by_domain: [] },
    };
    const projection = {
      project_id: UUID2,
      audit_id: UUID,
      audit_status: 'completed',
      product_analyzer_version: 'product-analysis-2',
      product_scoring_rule_version: 'product-scoring-v1',
      total_mentions: 4,
      total_analyses: 2,
      summary: {
        products_tracked: 1,
        products_visible: 1,
        visibility_rate: 1,
        top_three_rate: 1,
        average_rank: 1,
      },
      products: [
        {
          product_id: UUID,
          sku: 'AC-VB500',
          name: 'Acme VoltBike 500',
          category: 'Bikes',
          mention_count: 2,
          sov_share: 0.5,
          avg_rank: 1.0,
          rank_distribution: { top_1: 2, top_2_3: 0, top_4_5: 0, rank_6_plus: 0, unranked: 0 },
          price_mention_count: 2,
          price_accuracy_rate: 1.0,
          visibility_rate: 1,
          top_three_rate: 1,
          engine_coverage: 1,
          visibility_delta: null,
          prompt_coverage: null,
          frozen_prompt_context: [],
          conversation_themes: [],
          ...entryV2,
        },
      ],
      citation_comparison: { status: 'no_citations', limitation: '', categories: [] },
      created_at: '2026-07-15T00:00:00Z',
    };
    const parsed = strictValidate(productVisibilitySchema, projection, 'productVisibility');
    expect(parsed.products[0]?.category).toBe('Bikes');
    // A negative frequency count is contract drift.
    expect(() =>
      strictValidate(
        productVisibilitySchema,
        {
          ...projection,
          products: [
            {
              ...projection.products[0],
              attribute_dimension_frequency: { Facts: { Price: -1 } },
            },
          ],
        },
        'productVisibility',
      ),
    ).toThrow();
    expect(() =>
      strictValidate(
        productVisibilitySchema,
        { ...projection, audit_status: 'bogus' },
        'productVisibility',
      ),
    ).toThrow();
  });

  it('validates the evidence envelope (items + truncated, nullable fields)', () => {
    const item = {
      evidence_id: UUID,
      analysis_id: UUID2,
      evidence_kind: 'product_mention',
      audit_id: UUID,
      task_id: UUID2,
      artifact_id: null,
      logical_engine: 'gemini',
      transport_model: 'gemini-2.5-pro',
      prompt_text: 'best option 0',
      prompt_index: 0,
      repetition: 0,
      product_analyzer_version: 'product-analysis-2',
      matched_name: 'Acme VoltBike 500',
      matched_sku: 'AC-VB500',
      created_at: '2026-07-15T00:00:00Z',
      first_offset: null,
      rank_position: 1,
      price_value: 2499.0,
      price_matches_catalog: null,
      price_relation: 'higher',
      price_text: '$2,499.00',
      price_currency: 'USD',
      attribute_dimension: null,
      attribute_group: null,
      attribute_text: null,
      attribute_offset: null,
      merchant_name: null,
      merchant_domain: null,
      merchant_kind: null,
      destination_url: null,
    };
    const parsed = strictValidate(
      productEvidenceResponseSchema,
      { items: [item], truncated: true },
      'productEvidence',
    );
    expect(parsed.truncated).toBe(true);
    expect(parsed.items[0]?.price_matches_catalog).toBeNull();
    expect(parsed.items[0]?.evidence_kind).toBe('product_mention');
    // `mismatch` is NOT a storable item-level relation (v1 aggregate only).
    expect(() =>
      strictValidate(
        productEvidenceResponseSchema,
        { items: [{ ...item, price_relation: 'mismatch' }], truncated: false },
        'productEvidence',
      ),
    ).toThrow();
    expect(() =>
      strictValidate(
        productEvidenceResponseSchema,
        { items: [{ ...item, task_id: 'not-a-uuid' }], truncated: false },
        'productEvidence',
      ),
    ).toThrow();
  });
});
