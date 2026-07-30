import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { RotatingEngineLogos } from './rotating-engine-logos';

describe('RotatingEngineLogos', () => {
  it('renders the three primary and three alternate providers in fixed slots', () => {
    const { container } = render(<RotatingEngineLogos />);

    expect(
      screen.getByRole('img', {
        name: 'AI engines: ChatGPT, Gemini, Claude, Grok, Copilot and Perplexity',
      }),
    ).toBeInTheDocument();
    expect(container.querySelectorAll('[data-logo-slot]')).toHaveLength(3);
    expect(container.querySelectorAll('[data-logo-face="primary"]')).toHaveLength(3);
    expect(container.querySelectorAll('[data-logo-face="alternate"]')).toHaveLength(3);
  });

  it('claims no coverage the audited roster does not back', () => {
    render(<RotatingEngineLogos />);

    // The board is six marks and nothing more. Grok, Copilot and Perplexity are
    // the planned BYOK line-up, so the accessible name may NAME them but must
    // not tell a screen-reader user they are monitored/audited today.
    const board = screen.getByRole('img');
    expect(board.getAttribute('aria-label')).not.toMatch(/monitor|audit|track|cover/i);
  });
});
