import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { renderWithProviders } from '@/test/render';
import { BuyerPromptsPanel, CompetitorsPanel } from './commerce-panels';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
const TARGET_ID = '22222222-2222-4222-8222-222222222222';

function queries({ buyerPromptsError = false, buyerPromptsPending = false } = {}) {
  return {
    catalog: {
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
    expect(
      screen.getByRole('combobox', { name: 'Competitor discovery target' }),
    ).toBeInTheDocument();
    first.unmount();

    renderWithProviders(<BuyerPromptsPanel projectId={PROJECT_ID} queries={queryState as never} />);
    expect(screen.getByRole('combobox', { name: 'Buyer prompt target' })).toBeInTheDocument();
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
});
