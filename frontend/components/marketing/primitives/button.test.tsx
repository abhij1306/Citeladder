import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { IconButtonLink } from './button';

describe('IconButtonLink', () => {
  it('exposes its visual variant, icon, and new-tab behavior', () => {
    render(
      <IconButtonLink
        href="/demo"
        title="Try the demo"
        variant="dark"
        openInNewTab
        icon={<svg data-testid="custom-arrow" />}
      />,
    );

    // The label is announced once even though both badges carry the icon —
    // the duplicated badge is the travel illusion, not a second label.
    const link = screen.getByRole('link', { name: 'Try the demo' });
    expect(link).toHaveClass('citeladder-icon-btn', 'citeladder-icon-btn--dark');
    expect(link).toHaveAttribute('href', '/demo');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getAllByTestId('custom-arrow')).toHaveLength(2);
  });
});
