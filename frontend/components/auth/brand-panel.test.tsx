import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AuthWordmark } from './brand-panel';

describe('AuthWordmark', () => {
  it('is a named link back to the public home page', () => {
    const { container } = render(<AuthWordmark />);

    const link = screen.getByRole('link', { name: 'CiteLadder home' });
    expect(link).toHaveAttribute('href', '/');
    expect(container.querySelector('img')).toHaveAttribute(
      'src',
      expect.stringContaining('citeladder-logo.webp'),
    );
  });

  it('keeps its accessible name in the compact treatment', () => {
    render(<AuthWordmark compact />);

    expect(screen.getByRole('link', { name: 'CiteLadder home' })).toBeVisible();
  });
});
