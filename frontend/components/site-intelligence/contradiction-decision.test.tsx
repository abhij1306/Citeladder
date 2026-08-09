import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ContradictionGroup, CorrectionItem, KnowledgeAssertionItem } from '@/lib/api/types';
import { ContradictionDecision } from './contradiction-decision';

const { createCorrection, withdrawCorrection } = vi.hoisted(() => ({
  createCorrection: vi.fn(),
  withdrawCorrection: vi.fn(),
}));

vi.mock('@/lib/api/site-intelligence', () => ({
  siteIntelligenceApi: { createCorrection, withdrawCorrection },
}));

function side(id: string, value: number): KnowledgeAssertionItem {
  return {
    id,
    predicate_id: 'education.fee_amount',
    value_type: 'money',
    raw_value: String(value),
    normalized_value: `INR ${value.toFixed(2)}`,
    numeric_value: value,
    unit: 'annual',
    currency: 'INR',
    scope: { grade: '8', year: '2026' },
    scope_complete: true,
    temporal_state: 'current',
    effective_from: null,
    effective_to: null,
    derivation_method: 'visible_text',
    confidence: 1,
    review_state: 'observed',
    contradiction_group_id: 'conflict-1',
    evidence_refs: [{ source_kind: 'site_fetch_artifact', source_id: `source-${id}`, locator: {} }],
    subject: {
      id: 'entity-1',
      entity_type_id: 'education.organization',
      canonical_name: 'Example School',
    },
    effective_value: {
      raw_value: String(value),
      normalized_value: `INR ${value.toFixed(2)}`,
      numeric_value: value,
      unit: 'annual',
      currency: 'INR',
      value_type: 'money',
    },
    correction: null,
  };
}

function correction(): CorrectionItem {
  return {
    id: 'correction-1',
    target_kind: 'assertion',
    target_ref: {},
    target_field: 'value',
    source_crawl_id: 'crawl-1',
    source_target_id: 'assertion-1',
    derived_value: {},
    corrected_value: { normalized_value: 'INR 260000.00', numeric_value: 260000 },
    value_type: 'money',
    effective_scope: 'project',
    effective_scope_ref: {},
    effective_from: null,
    effective_to: null,
    author_user_id: 'user-1',
    reason: 'Confirmed by finance.',
    state: 'active',
    withdrawn_at: null,
    created_at: '2026-08-09T00:00:00Z',
    transitions: [],
  };
}

function group(activeCorrection: CorrectionItem | null = null): ContradictionGroup {
  return {
    contradiction_group_id: 'conflict-1',
    predicate_id: 'education.fee_amount',
    scope: { grade: '8', year: '2026' },
    subject: {
      id: 'entity-1',
      entity_type_id: 'education.organization',
      canonical_name: 'Example School',
    },
    resolution_state: activeCorrection ? 'corrected' : 'unresolved',
    correction: activeCorrection,
    sides: [side('assertion-1', 250000), side('assertion-2', 275000)],
  };
}

function renderDecision(value: ContradictionGroup) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ContradictionDecision projectId="project-1" group={value} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  createCorrection.mockResolvedValue(correction());
  withdrawCorrection.mockResolvedValue({ ...correction(), state: 'withdrawn' });
});

describe('ContradictionDecision', () => {
  it('keeps every observed side visible and saves an inline correction with a reason', async () => {
    renderDecision(group());

    expect(screen.getByText('INR 250000.00')).toBeInTheDocument();
    expect(screen.getByText('INR 275000.00')).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole('button', { name: 'Use this value' })[0]);
    await userEvent.type(
      screen.getByLabelText('Why is this the effective value?'),
      'Confirmed by finance.',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Save correction' }));

    await waitFor(() =>
      expect(createCorrection).toHaveBeenCalledWith('project-1', {
        target_kind: 'assertion',
        target_id: 'assertion-1',
        value: 250000,
        effective_scope: 'project',
        unit: 'annual',
        currency: 'INR',
        reason: 'Confirmed by finance.',
      }),
    );
    expect(screen.getByText('INR 250000.00')).toBeInTheDocument();
    expect(screen.getByText('INR 275000.00')).toBeInTheDocument();
  });

  it('requires a reason before withdrawing a correction', async () => {
    renderDecision(group(correction()));

    const button = screen.getByRole('button', { name: 'Withdraw correction' });
    expect(button).toBeDisabled();
    await userEvent.type(
      screen.getByLabelText('Reason for withdrawal'),
      'The recrawl now has the corrected amount.',
    );
    await userEvent.click(button);

    await waitFor(() =>
      expect(withdrawCorrection).toHaveBeenCalledWith(
        'project-1',
        'correction-1',
        'The recrawl now has the corrected amount.',
      ),
    );
  });
});
