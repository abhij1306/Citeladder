import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { WallpaperPanel } from './wallpaper-panel';

describe('WallpaperPanel', () => {
  it('omits its default radius for edge-to-edge callers', () => {
    const { container } = render(
      <WallpaperPanel rounded={false}>
        <span>Scene</span>
      </WallpaperPanel>,
    );

    expect(screen.getByText('Scene').parentElement).not.toHaveClass('rounded-lg');
    expect(container.querySelector('.brand-atmosphere')).toBeNull();
  });
});
