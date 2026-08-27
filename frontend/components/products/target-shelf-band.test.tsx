import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { TargetShelfBand } from './target-shelf-band';

function shelfQuery(snapshot: Record<string, number | null> | undefined) {
  return {
    isPending: false,
    isError: false,
    data: { snapshots: snapshot ? [snapshot] : [] },
  } as never;
}

describe('TargetShelfBand', () => {
  it('renders unavailable metrics with the compact shared state treatment', () => {
    render(<TargetShelfBand query={shelfQuery(undefined)} />);

    for (const value of screen.getAllByText('Not measured')) {
      expect(value).toHaveClass('text-xs', 'font-medium');
      expect(value.tagName).not.toBe('H3');
    }
  });

  it('keeps observed values in the KPI heading role', () => {
    render(
      <TargetShelfBand
        query={shelfQuery({
          product_visibility: 0.25,
          share_of_shelf: 0.5,
          average_shelf_position: 2,
          first_position_win_rate: 0,
        })}
      />,
    );

    expect(screen.getByRole('heading', { name: '25.0%' })).toBeVisible();
    expect(screen.getByRole('heading', { name: '0.0%' })).toBeVisible();
  });
});
