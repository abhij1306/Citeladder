import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { RotatingEngineLogos } from './rotating-engine-logos';

describe('RotatingEngineLogos', () => {
  it('discloses all six brands without status labels or connect affordances', () => {
    const { container } = render(<RotatingEngineLogos />);
    const roster = screen.getByRole('img');

    expect(roster).toHaveAccessibleName('ChatGPT, Grok, Gemini, Copilot, Claude and Perplexity.');
    expect(screen.queryByText(/available|coming soon/i)).not.toBeInTheDocument();
    expect(container.querySelectorAll('.engine-rotor-slot')).toHaveLength(3);
    expect(container.querySelectorAll('.engine-rotor-face')).toHaveLength(6);
    expect(container.querySelectorAll('a, button')).toHaveLength(0);
  });
});
