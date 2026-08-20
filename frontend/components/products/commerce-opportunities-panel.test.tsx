import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { CommerceOpportunitiesPanel } from './commerce-opportunities-panel';

describe('CommerceOpportunitiesPanel', () => {
  it('confirms an action in memory without calling a mutation', async () => {
    const user = userEvent.setup();
    const opportunity = {
      id: '11111111-1111-4111-8111-111111111111',
      title: 'Add missing warranty details',
      target_label: 'Summit 40L',
      severity: 'high',
    };
    const queries = {
      opportunitiesQuery: {
        isLoading: false,
        isError: false,
        data: { items: [opportunity] },
      },
    };

    render(<CommerceOpportunitiesPanel queries={queries as never} />);
    await user.click(screen.getByRole('button', { name: /add missing warranty details/i }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(screen.getByText('Confirmed')).toBeInTheDocument();
    expect(queries).not.toHaveProperty('mutation');
  });
});
