import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { RotatingEngineLogos } from './rotating-engine-logos';

describe('RotatingEngineLogos', () => {
  it('renders the three primary and three alternate providers in fixed slots', () => {
    const { container } = render(<RotatingEngineLogos />);

    expect(
      screen.getByRole('img', {
        name: 'Searchify monitors ChatGPT, Gemini, Claude, Grok, Copilot and Perplexity',
      }),
    ).toBeInTheDocument();
    expect(container.querySelectorAll('[data-logo-slot]')).toHaveLength(3);
    expect(container.querySelectorAll('[data-logo-face="primary"]')).toHaveLength(3);
    expect(container.querySelectorAll('[data-logo-face="alternate"]')).toHaveLength(3);
  });
});
