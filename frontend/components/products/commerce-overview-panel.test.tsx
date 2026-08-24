import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { useCommerceOverview } from '@/lib/products/use-products-screen';

import { CommerceOverviewPanel } from './commerce-overview-panel';

type OverviewQueries = ReturnType<typeof useCommerceOverview>;

function queriesWith(prompts: Array<{ topic_id: string; intent: string }>): OverviewQueries {
  return {
    visibilityQuery: { isLoading: false, isError: false, data: undefined },
    productsQuery: { isLoading: false, isError: false, data: [{ sku: 'SKU-1' }] },
    missingCategorySkus: [],
    categories: ['Books', 'Games'],
    topicsQuery: {
      data: [
        { id: 'topic-books', name: 'books' },
        { id: 'topic-games', name: 'Games' },
      ],
    },
    commercePromptSet: {
      prompts: prompts.map((prompt, index) => ({
        ...prompt,
        id: `prompt-${index}`,
        cohort: 'commerce',
        status: 'active',
      })),
    },
    generatePromptsMutation: {
      mutate: vi.fn(),
      isPending: false,
      isError: false,
    },
    commerceAudits: [],
  } as unknown as OverviewQueries;
}

describe('CommerceOverviewPanel prompt gating', () => {
  it('stays in generation until every category has both required intents', () => {
    render(
      <CommerceOverviewPanel
        queries={queriesWith([
          { topic_id: 'topic-books', intent: 'discovery' },
          { topic_id: 'topic-books', intent: 'comparison' },
          { topic_id: 'topic-games', intent: 'discovery' },
        ])}
        onSelectTab={vi.fn()}
        onLaunchAudit={vi.fn()}
      />,
    );

    expect(
      screen.getByRole('heading', { name: 'Generate product visibility prompts' }),
    ).toBeTruthy();
  });

  it('allows the first audit after every category has both required intents', () => {
    render(
      <CommerceOverviewPanel
        queries={queriesWith([
          { topic_id: 'topic-books', intent: 'discovery' },
          { topic_id: 'topic-books', intent: 'comparison' },
          { topic_id: 'topic-games', intent: 'discovery' },
          { topic_id: 'topic-games', intent: 'comparison' },
        ])}
        onSelectTab={vi.fn()}
        onLaunchAudit={vi.fn()}
      />,
    );

    expect(
      screen.getByRole('heading', { name: 'Run your first Commerce visibility audit' }),
    ).toBeTruthy();
  });
});
