import { act, fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/render';

import { AgentConsole } from './agent-console';
import { PROMPT_MS, SCRIPT, THINKING_MS } from './agent-console/data';

const motionPreference = vi.hoisted(() => ({ reduced: false }));

vi.mock('motion/react', async (importOriginal) => ({
  ...(await importOriginal<typeof import('motion/react')>()),
  useReducedMotion: () => motionPreference.reduced,
}));

afterEach(() => {
  motionPreference.reduced = false;
  vi.useRealTimers();
});

describe('AgentConsole', () => {
  it('switches the active layer without changing its public export', () => {
    renderWithProviders(<AgentConsole />);

    const content = screen.getByRole('button', { name: /Content Intelligence/i });
    fireEvent.click(content);

    expect(content).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /Site Health/i })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('shows the complete, static transcript when motion is reduced', () => {
    motionPreference.reduced = true;
    renderWithProviders(<AgentConsole />);

    for (const step of SCRIPT) {
      expect(screen.getByText(step.prompt)).toBeInTheDocument();
      expect(screen.getByText(step.reply)).toBeInTheDocument();
    }
  });

  it('keeps a completed reply visible while its transcript is hovered', () => {
    vi.useFakeTimers();
    renderWithProviders(<AgentConsole />);

    act(() => vi.advanceTimersByTime(SCRIPT[0].prompt.length * PROMPT_MS + 500));
    const transcript = screen.getByTestId('growth-agent-preview');
    fireEvent.mouseEnter(transcript);
    act(() => vi.advanceTimersByTime(THINKING_MS));

    expect(screen.getByText(SCRIPT[0].reply)).toBeInTheDocument();
    fireEvent.mouseLeave(transcript);
  });
});
