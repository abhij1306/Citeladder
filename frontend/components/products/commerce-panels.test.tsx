import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { renderWithProviders } from '@/test/render';
import {
  BuyerPromptsPanel,
  CompetitorsPanel,
  ShelfPanel,
  competitorHost,
  discoveryMessage,
} from './commerce-panels';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
const TARGET_ID = '22222222-2222-4222-8222-222222222222';

function queries({ buyerPromptsError = false, buyerPromptsPending = false } = {}) {
  return {
    catalog: {
      isLoading: false,
      isError: false,
      data: {
        categories: [{ id: TARGET_ID, name: 'Running shoes' }],
        products: [],
      },
    },
    competitors: { data: [], isError: false },
    buyerPrompts: {
      data: buyerPromptsError || buyerPromptsPending ? undefined : [],
      isError: buyerPromptsError,
      isPending: buyerPromptsPending,
      isSuccess: !buyerPromptsError && !buyerPromptsPending,
    },
    shelf: { data: undefined, isError: false },
  };
}

describe('Commerce panels', () => {
  it('labels target selectors for their distinct workflows', () => {
    const queryState = queries();
    const first = renderWithProviders(
      <CompetitorsPanel projectId={PROJECT_ID} queries={queryState as never} />,
    );
    // Both panels take MANY targets now, so the control is a checkbox menu
    // rather than a single-choice select.
    expect(
      screen.getByRole('button', { name: 'Competitor discovery targets' }),
    ).toBeInTheDocument();
    first.unmount();

    renderWithProviders(<BuyerPromptsPanel projectId={PROJECT_ID} queries={queryState as never} />);
    expect(screen.getByRole('button', { name: 'Buyer prompt targets' })).toBeInTheDocument();
  });

  it('shows a buyer-prompt read error instead of an unexplained empty table', () => {
    renderWithProviders(
      <BuyerPromptsPanel
        projectId={PROJECT_ID}
        queries={queries({ buyerPromptsError: true }) as never}
      />,
    );

    expect(screen.getByText('Buyer prompts could not be loaded.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('does not render the buyer-prompts table while the query is pending', () => {
    renderWithProviders(
      <BuyerPromptsPanel
        projectId={PROJECT_ID}
        queries={queries({ buyerPromptsPending: true }) as never}
      />,
    );

    expect(screen.getByText('Loading persisted buyer prompts…')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('requires an explicit AI Shelf target before loading metrics', () => {
    renderWithProviders(
      <ShelfPanel queries={queries() as never} onTargetChange={() => undefined} />,
    );

    expect(screen.getByRole('combobox', { name: 'AI Shelf target' })).toHaveValue('');
    expect(screen.getByText(/select one product or category/i)).toBeInTheDocument();
  });
});

describe('Discovery status copy', () => {
  it('reads as a sentence instead of interpolating the raw status', () => {
    // Shipped as "Discovery for this category is succeeded".
    expect(discoveryMessage('succeeded', 'category', '')).toBe(
      'Discovery finished for this category.',
    );
    expect(discoveryMessage('running', 'category', '')).toBe(
      'Finding competitors for this category…',
    );
  });

  it('explains the two failures a person can act on', () => {
    expect(discoveryMessage('failed', 'category', 'unusable_target')).toContain(
      'needs a clearer name',
    );
    expect(discoveryMessage('failed', 'category', 'provider_unavailable')).toContain(
      'not configured',
    );
  });

  it('identifies a candidate by domain, not by its page title', () => {
    expect(competitorHost('https://www.rival.test/products/linen-dress')).toBe('rival.test');
    expect(competitorHost('not a url')).toBe('not a url');
  });
});
