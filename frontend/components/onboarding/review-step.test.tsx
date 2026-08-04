import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ReviewStep } from './review-step';

describe('ReviewStep competitor limit', () => {
  it('shows the backend limit and disables additions at five selected competitors', async () => {
    const add = vi.fn();
    render(
      <ReviewStep
        domains={[]}
        competitors={Array.from({ length: 5 }, (_, index) => ({
          id: `competitor-${index}`,
          name: `Competitor ${index + 1}`,
          aliases: [],
          domains: [],
          selected: true,
        }))}
        prompts={[]}
        maximumCompetitors={5}
        onToggleDomain={vi.fn()}
        onToggleCompetitor={vi.fn()}
        onTogglePrompt={vi.fn()}
        onEditPrompt={vi.fn()}
        onRenameCompetitor={vi.fn()}
        onAddCompetitor={add}
      />,
    );

    expect(screen.getByText('5 of 5')).toBeInTheDocument();
    const button = screen.getByRole('button', { name: 'Add competitor' });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(add).not.toHaveBeenCalled();
  });
});
