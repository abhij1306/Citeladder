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

  it('uses brand colors and a tightly sequenced three-slot flip', () => {
    const { container } = render(<RotatingEngineLogos />);
    const rotors = [...container.querySelectorAll<HTMLElement>('.engine-rotor-inner')];

    expect(rotors.map((rotor) => rotor.style.animationDelay)).toEqual(['0ms', '120ms', '240ms']);
    expect(container.querySelector('[data-engine-logo="claude"]')).toHaveClass('text-brand-claude');
    expect(container.querySelector('#copilot-brand-gradient')).toBeInTheDocument();
    expect(container.querySelectorAll('.engine-rotor-face .text-base')).toHaveLength(6);
  });
});
