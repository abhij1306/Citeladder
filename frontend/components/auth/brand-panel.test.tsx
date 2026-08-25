import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AuthBrandPanel, AuthWordmark, BrandCanvas } from './brand-panel';

/**
 * `components/auth` had no colocated tests.
 *
 * `BrandCanvas` is shared by auth AND onboarding precisely so the two surfaces
 * cannot drift apart, so what is worth pinning is the contract that makes the
 * sharing safe: the ambient glow/ribbon geometry is decoration and must stay
 * hidden from assistive technology, and the wordmark must remain a real link
 * home with an accessible name in both the light and dark treatments.
 */
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

  it('keeps its accessible name on the dark canvas treatment', () => {
    // The dark-canvas variant must not change what a screen reader hears.
    render(<AuthWordmark light />);

    expect(screen.getByRole('link', { name: 'CiteLadder home' })).toBeVisible();
  });

  it('keeps its accessible name in the compact treatment', () => {
    render(<AuthWordmark compact />);

    expect(screen.getByRole('link', { name: 'CiteLadder home' })).toBeVisible();
  });
});

describe('BrandCanvas', () => {
  it('renders caller content', () => {
    render(
      <BrandCanvas>
        <p>Set up your project</p>
      </BrandCanvas>,
    );

    expect(screen.getByText('Set up your project')).toBeVisible();
  });

  it('hides the ambient decoration from assistive technology', () => {
    const { container } = render(
      <BrandCanvas>
        <p>Content</p>
      </BrandCanvas>,
    );

    // Four decorative glow/ribbon layers with no meaning; announcing them
    // would put four empty nodes in front of the actual content.
    const decoration = container.querySelector('[aria-hidden="true"]');
    expect(decoration).not.toBeNull();
    expect(decoration).toHaveClass('pointer-events-none');
  });

  it('marks itself so the shared surface is identifiable', () => {
    const { container } = render(
      <BrandCanvas>
        <p>Content</p>
      </BrandCanvas>,
    );

    expect(container.querySelector('[data-brand-canvas="true"]')).not.toBeNull();
  });

  it('merges a caller class onto the canvas rather than replacing it', () => {
    const { container } = render(
      <BrandCanvas className="col-span-5">
        <p>Content</p>
      </BrandCanvas>,
    );

    const canvas = container.querySelector('[data-brand-canvas="true"]');
    expect(canvas).toHaveClass('col-span-5');
    // Dropping the base classes would lose the dark treatment entirely.
    expect(canvas).toHaveClass('bg-brand-canvas');
  });
});

describe('AuthBrandPanel', () => {
  it('presents the wordmark on the shared canvas', () => {
    const { container } = render(<AuthBrandPanel />);

    expect(container.querySelector('[data-brand-canvas="true"]')).not.toBeNull();
    expect(screen.getByRole('link', { name: 'CiteLadder home' })).toBeVisible();
  });
});
