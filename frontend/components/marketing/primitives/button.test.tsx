import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ArrowRight } from 'lucide-react';

import { ButtonLink, IconButtonLink } from './button';

describe('IconButtonLink', () => {
  it('uses the shared button primitive with its icon and new-tab behavior', () => {
    render(
      <IconButtonLink
        href="/demo"
        title="Try the demo"
        variant="dark"
        openInNewTab
        icon={<svg data-testid="custom-arrow" />}
      />,
    );

    const link = screen.getByRole('link', { name: 'Try the demo' });
    expect(link).toHaveClass('focus-ring', 'bg-panel', 'shadow-card');
    expect(link).toHaveAttribute('href', '/demo');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getAllByTestId('custom-arrow')).toHaveLength(1);
  });

  it('sizes and aligns link-button icons consistently', () => {
    render(
      <ButtonLink href="/demo">
        Book a demo
        <ArrowRight aria-hidden />
      </ButtonLink>,
    );

    expect(screen.getByRole('link', { name: 'Book a demo' })).toHaveClass(
      '[&_svg]:size-4',
      '[&_svg]:shrink-0',
    );
  });
});
