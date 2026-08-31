import { describe, expect, it } from 'vitest';

import type { BrandDiscovery } from '@/lib/api/brand-discoveries';

import { discoveryActivity } from './discovery-activity';

function discovery(phase: BrandDiscovery['progress']['phase']): BrandDiscovery {
  return {
    id: '5bc3f26d-cab8-4e87-a3f2-2d30f1341f10',
    workspace_id: 'f0265ca6-78dd-40c9-aae2-75bca60eb6cc',
    project_id: null,
    status: phase === 'complete' ? 'ready' : 'running',
    progress: {
      phase,
      completed_steps: 2,
      total_steps: 4,
      pages_read: 3,
      competitors_found: 2,
      prompts_prepared: 0,
    },
    input_data: {},
    profile: {
      description: '',
      positioning: '',
      products_services: [],
      target_audience: '',
      industry: '',
      business_type: 'b2b',
      price_tier: 'unknown',
      field_confidence: {},
      category: '',
      category_options: [],
      category_aliases: [],
      category_terms: [],
      jobs_to_be_done: [],
      sector: 'Other',
      business_model: 'd2c_product',
      secondary_business_models: [],
      market_scope: 'national',
      buyer_register: 'research_comparative',
      buyer_roles: [],
      service_areas: [],
      knowledge_strength: 'none',
    },
    domains: [],
    competitors: [],
    topics: [],
    prompt_suggestions: [],
    evidence: [],
    warnings: [],
    gaps: [],
    error_code: '',
    created_at: '2026-08-04T10:00:00Z',
    updated_at: '2026-08-04T10:00:00Z',
  };
}

describe('discoveryActivity', () => {
  it('maps persisted phases to a fixed customer-facing vocabulary', () => {
    const steps = discoveryActivity(discovery('finding_competitors'));

    expect(steps.map((step) => step.label)).toEqual([
      'Opening your website',
      'Understanding what you offer',
      'Finding comparable brands',
      'Preparing your review',
    ]);
    expect(steps.map((step) => step.state)).toEqual(['complete', 'complete', 'active', 'pending']);
    expect(JSON.stringify(steps)).not.toMatch(/finding_competitors|queue|provider/);
  });

  it('uses backend counts without inventing time or percentages', () => {
    const steps = discoveryActivity(discovery('preparing_review'));

    expect(steps[0]?.detail).toBe('3 useful pages read');
    expect(steps[2]?.detail).toBe('2 comparable brands found');
  });

  it('gives every research step a simple customer-facing subtitle', () => {
    const steps = discoveryActivity(undefined);

    expect(steps.map((step) => step.detail)).toEqual([
      'Checking that your website can be read.',
      'Learning what you offer and who it is most useful for.',
      'Looking for genuinely comparable brands.',
      'Organizing the strongest findings for your review.',
    ]);
  });
});
