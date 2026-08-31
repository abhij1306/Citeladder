import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ReviewStep } from './review-step';

vi.mock('@/lib/brand/logo-dev', () => ({
  logoDevUrl: (websiteUrl?: string | null) =>
    websiteUrl ? `https://logos.example/${websiteUrl}` : null,
}));

describe('ReviewStep competitor limit', () => {
  it('stacks websites and competitors as flat ruled flow groups', () => {
    render(
      <ReviewStep
        domains={[]}
        competitors={[]}
        maximumCompetitors={5}
        onToggleDomain={vi.fn()}
        onToggleCompetitor={vi.fn()}
        onEditCompetitorDomain={vi.fn()}
        onAddCompetitor={vi.fn()}
      />,
    );

    const websites = screen.getByRole('heading', { name: 'Your websites' });
    const competitors = screen.getByRole('heading', { name: 'Competitors' });
    expect(websites).toHaveClass('flow-group-title');
    expect(competitors).toHaveClass('flow-group-title');
    expect(websites.closest('section')?.parentElement).toBe(
      competitors.closest('section')?.parentElement,
    );
    expect(websites.closest('section')?.parentElement).toHaveClass('flow-groups');
    expect(competitors.closest('section')).toHaveClass('flow-group');
    expect(screen.getByText('Auto-verified from your domain.')).toHaveClass('flow-help');
  });

  it('shows only the competitor URL beneath its name', () => {
    const { container } = render(
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
    expect(container.querySelector('img')?.getAttribute('src')).toContain(
      'https://logos.example/kmart.com.au',
    );
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

    expect(screen.getByText('5 of 5')).toBeInTheDocument();
    expect(screen.getByText('Tracked head-to-head in every answer.')).toHaveClass('flow-help');
    const button = screen.getByRole('button', { name: 'Add' });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(add).not.toHaveBeenCalled();
  });
});
