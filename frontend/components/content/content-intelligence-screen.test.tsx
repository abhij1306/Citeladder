import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';

import { ContentIntelligenceScreen } from './content-intelligence-screen';

const mocks = vi.hoisted(() => ({
  content: {} as Record<string, unknown>,
}));

vi.mock('@/lib/project/project-context', () => ({
  useActiveProject: () => ({ id: '11111111-1111-4111-8111-111111111111' }),
}));

vi.mock('@/lib/content/use-content-intelligence', () => ({
  useContentIntelligence: () => mocks.content,
}));

vi.mock('@/components/content/content-screen', () => ({
  ContentScreen: () => <div>Custom task composer</div>,
}));

function mutation() {
  return { isPending: false, isError: false, mutate: vi.fn(), mutateAsync: vi.fn() };
}

function query(data: unknown) {
  return { data, isLoading: false };
}

beforeEach(() => {
  mocks.content = {
    strategyQuery: query(null),
    inventoryQuery: query([]),
    briefsQuery: query([]),
    revisionsQuery: query([]),
    verificationsQuery: query([]),
    recomputeMutation: mutation(),
    createBriefMutation: mutation(),
    generateBriefMutation: mutation(),
    createRevisionMutation: mutation(),
    updateRevisionMutation: mutation(),
    transitionRevisionMutation: mutation(),
    verifyRevisionMutation: mutation(),
    exportRevisionMutation: mutation(),
  };
});

describe('ContentIntelligenceScreen', () => {
  it('renders an evidence-first strategy with explicit limitations', () => {
    mocks.content.strategyQuery = query({
      inventory_summary: { total: 4 },
      coverage: {
        questions: [
          { question_id: 'fees', state: 'missing' },
          { question_id: 'dates', state: 'conflicting' },
        ],
      },
      priorities: [
        {
          question_id: 'dates',
          state: 'conflicting',
          score: 100,
          reason: 'Current sources disagree.',
        },
      ],
      limitations: ['demand_evidence_unavailable'],
    });

    render(<ContentIntelligenceScreen panel="strategy" />);

    expect(screen.getByText('Evidence into a sequenced content program')).toBeInTheDocument();
    expect(screen.getByText('conflicting')).toBeInTheDocument();
    expect(screen.getByText(/demand_evidence_unavailable/)).toBeInTheDocument();
  });

  it('keeps a blocked revision visible but prevents save', () => {
    mocks.content.revisionsQuery = query([
      {
        id: '22222222-2222-4222-8222-222222222222',
        state: 'edited',
        visible_content: 'Admissions answer',
        publication_target_url: '',
        validation_snapshot: { status: 'blocked' },
      },
    ]);

    render(<ContentIntelligenceScreen panel="revisions" />);

    expect(screen.getByText('blocked')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save revision' })).toBeDisabled();
    expect(screen.getByText(/does not make any sentence a project fact/i)).toBeInTheDocument();
  });

  it('keeps the advanced custom task inside Drafts', () => {
    render(<ContentIntelligenceScreen panel="drafts" />);
    expect(screen.getByText('Custom task composer')).toBeInTheDocument();
  });

  it('switches revision drafts safely and preserves structured data on edit', async () => {
    const updateMutation = mutation();
    mocks.content.updateRevisionMutation = updateMutation;
    mocks.content.revisionsQuery = query([
      {
        id: '22222222-2222-4222-8222-222222222222',
        state: 'edited',
        visible_content: 'Admissions answer',
        structured_data: { '@type': 'FAQPage', mainEntity: [] },
        publication_target_url: '',
        validation_snapshot: { status: 'passed' },
      },
      {
        id: '33333333-3333-4333-8333-333333333333',
        state: 'edited',
        visible_content: 'Fees answer',
        structured_data: { '@type': 'FAQPage', mainEntity: [{ name: 'Fees' }] },
        publication_target_url: '',
        validation_snapshot: { status: 'passed' },
      },
    ]);
    const user = userEvent.setup();

    render(<ContentIntelligenceScreen panel="revisions" />);
    await user.click(screen.getByRole('button', { name: /Fees answer/ }));

    expect(screen.getByRole('textbox', { name: 'Visible content' })).toHaveValue('Fees answer');
    await user.click(screen.getByRole('button', { name: 'Save edit' }));
    expect(updateMutation.mutate).toHaveBeenCalledWith({
      revisionId: '33333333-3333-4333-8333-333333333333',
      visibleContent: 'Fees answer',
      structuredData: { '@type': 'FAQPage', mainEntity: [{ name: 'Fees' }] },
    });
  });
});
