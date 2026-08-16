import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ReviewStep } from './review-step';

describe('ReviewStep competitor limit', () => {
  it('shows only the competitor URL beneath its name', () => {
    render(
      <ReviewStep
        domains={[]}
        competitors={[
          {
            id: 'competitor-1',
            name: 'Kmart Australia',
            aliases: [],
            domains: ['kmart.com.au'],
            reasoning: 'A long generated competitor explanation.',
            evidence_urls: ['https://example.com/evidence'],
            selected: true,
          },
        ]}
        maximumCompetitors={5}
        onToggleDomain={vi.fn()}
        onToggleCompetitor={vi.fn()}
        onEditCompetitorDomain={vi.fn()}
        onAddCompetitor={vi.fn()}
      />,
    );

    expect(screen.queryByText('A long generated competitor explanation.')).not.toBeInTheDocument();
    expect(screen.queryByText(/Supporting links available/)).not.toBeInTheDocument();
    expect(screen.queryByText('https://example.com/evidence')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'https://kmart.com.au' })).toHaveAttribute(
      'href',
      'https://kmart.com.au',
    );
  });

  it('preserves an existing competitor URL scheme without duplication', () => {
    render(
      <ReviewStep
        domains={[]}
        competitors={[
          {
            id: 'competitor-1',
            name: 'Example competitor',
            aliases: [],
            domains: ['http://competitor.example'],
            selected: true,
          },
        ]}
        maximumCompetitors={5}
        onToggleDomain={vi.fn()}
        onToggleCompetitor={vi.fn()}
        onEditCompetitorDomain={vi.fn()}
        onAddCompetitor={vi.fn()}
      />,
    );

    const link = screen.getByRole('link', { name: 'http://competitor.example' });
    expect(link).toHaveAttribute('href', 'http://competitor.example');
    expect(screen.queryByText('https://http://competitor.example')).not.toBeInTheDocument();
  });

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
        maximumCompetitors={5}
        onToggleDomain={vi.fn()}
        onToggleCompetitor={vi.fn()}
        onEditCompetitorDomain={vi.fn()}
        onAddCompetitor={add}
      />,
    );

    expect(screen.getByText('5 of 5 tracked')).toBeInTheDocument();
    const button = screen.getByRole('button', { name: 'Add' });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(add).not.toHaveBeenCalled();
  });
});
