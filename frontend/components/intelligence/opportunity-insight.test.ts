import { describe, expect, it } from 'vitest';

import type { Opportunity } from '@/lib/api/types';

import { insightFromOpportunity } from './opportunity-insight';

function opportunity(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: 'opp-1',
    project_id: 'proj-1',
    rule_id: 'missing_faq',
    opportunity_type: 'site',
    severity: 'high',
    priority_score: 82,
    title: '47 product pages have weak buying-intent coverage',
    target_key: 'products',
    target_prompt_id: null,
    target_url: null,
    target_theme: null,
    target_label: '47 pages · /products/*',
    status: 'open',
    system_rank: 1,
    display_rank: 1,
    order_source: 'system',
    priority_factors: {},
    evidence_summary: { count: 47, kinds: ['crawl'] },
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    ...overrides,
  } as Opportunity;
}

describe('insightFromOpportunity', () => {
  it('maps severity to the deterministic priority band', () => {
    expect(insightFromOpportunity(opportunity({ severity: 'critical' })).priority).toBe('high');
    expect(insightFromOpportunity(opportunity({ severity: 'medium' })).priority).toBe('medium');
    expect(insightFromOpportunity(opportunity({ severity: 'low' })).priority).toBe('low');
  });

  it('routes each opportunity type to its owning layer', () => {
    // The backend enum is closed, so this covers every member.
    expect(insightFromOpportunity(opportunity({ opportunity_type: 'topic' })).layer).toBe(
      'content',
    );
    expect(insightFromOpportunity(opportunity({ opportunity_type: 'visibility' })).layer).toBe(
      'demand',
    );
    expect(insightFromOpportunity(opportunity({ opportunity_type: 'traffic' })).layer).toBe(
      'demand',
    );
    expect(insightFromOpportunity(opportunity({ opportunity_type: 'site' })).layer).toBe('site');
  });

  it('yields no evidence when nothing backs the claim', () => {
    // The Insight component then declines to render it, per §5.
    const insight = insightFromOpportunity(
      opportunity({ evidence_summary: { count: 0, kinds: [] } }),
    );
    expect(insight.evidence).toBeNull();
  });

  it('keeps the server id so the same insight is the same cache identity', () => {
    expect(insightFromOpportunity(opportunity({ id: 'shared-9' })).id).toBe('shared-9');
  });

  it('falls back to counts when no target label exists', () => {
    const insight = insightFromOpportunity(opportunity({ target_label: null }));
    expect(insight.evidence?.label).toBe('47 items · crawl');
  });
});
