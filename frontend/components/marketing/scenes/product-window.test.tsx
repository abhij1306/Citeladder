import { act, fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/render';

import { PREVIEW_HOLD_MS, PREVIEW_STEP_MS, ProductWindow } from './product-window';

const motionPreference = vi.hoisted(() => ({ reduced: false }));

vi.mock('motion/react', async (importOriginal) => ({
  ...(await importOriginal<typeof import('motion/react')>()),
  useReducedMotion: () => motionPreference.reduced,
}));

afterEach(() => {
  motionPreference.reduced = false;
  vi.useRealTimers();
});

describe('ProductWindow', () => {
  it('uses the real four-layer hierarchy and current product navigation', async () => {
    renderWithProviders(<ProductWindow />);

    for (const label of [
      'Site Health',
      'Content Intelligence',
      'Demand Intelligence',
      'Growth Agent',
    ]) {
      expect(screen.getByRole('tab', { name: label })).toBeInTheDocument();
    }

    expect(screen.getByRole('tab', { name: 'Site Health' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(document.querySelector('[data-preview-layer="site"]')).not.toBeNull();
    screen.getAllByText('Opportunities');
    const sidebar = screen.getByRole('navigation', { name: 'Product preview navigation' });
    expect(within(sidebar).queryByText('Growth Agent')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Agent' })).toBeInTheDocument();
    expect(within(sidebar).getByText('AI Visibility')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: 'Demand Intelligence' }));
    expect(document.querySelector('[data-preview-layer="demand"]')).not.toBeNull();
    expect(within(sidebar).getByText('Website')).toBeInTheDocument();
    expect(within(sidebar).queryByText('Search Demand')).not.toBeInTheDocument();
    expect(within(sidebar).getByText('AI Visibility').closest('div')).toHaveClass('bg-accent-soft');
    screen.getAllByText('AI Visibility');
    screen.getAllByText('Traffic');
    screen.getAllByText('Prompts');
  });

  it('advances to the next layer after the active prototype finishes', () => {
    vi.useFakeTimers();
    renderWithProviders(<ProductWindow />);

    for (let step = 0; step < 3; step += 1) {
      act(() => vi.advanceTimersByTime(PREVIEW_STEP_MS));
    }
    act(() => vi.advanceTimersByTime(PREVIEW_HOLD_MS));

    expect(screen.getByRole('tab', { name: 'Content Intelligence' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(document.querySelector('[data-preview-layer="content"]')).not.toBeNull();
  });

  it('pauses and resumes the active preview phase', () => {
    vi.useFakeTimers();
    renderWithProviders(<ProductWindow />);

    fireEvent.click(screen.getByRole('tab', { name: 'Demand Intelligence' }));
    const demand = within(document.querySelector('[data-preview-layer="demand"]') as HTMLElement);
    expect(demand.getByText('Trends')).toHaveAttribute('aria-current', 'page');

    fireEvent.click(screen.getByRole('button', { name: 'Pause product preview' }));
    act(() => vi.advanceTimersByTime(PREVIEW_STEP_MS * 2));
    expect(demand.getByText('Trends')).toHaveAttribute('aria-current', 'page');

    fireEvent.click(screen.getByRole('button', { name: 'Play product preview' }));
    act(() => vi.advanceTimersByTime(PREVIEW_STEP_MS));
    expect(demand.getByText('Mentions & Citations')).toHaveAttribute('aria-current', 'page');
  });

  it('pins the preview to its final phase when reduced motion is enabled', () => {
    motionPreference.reduced = true;
    renderWithProviders(<ProductWindow />);

    fireEvent.click(screen.getByRole('tab', { name: 'Demand Intelligence' }));
    const demand = within(document.querySelector('[data-preview-layer="demand"]') as HTMLElement);

    expect(screen.getByRole('button', { name: 'Motion reduced' })).toBeDisabled();
    expect(demand.getByText('Query Fanout')).toHaveAttribute('aria-current', 'page');
  });

  it('starts a full phase interval after manual layer selection', () => {
    vi.useFakeTimers();
    renderWithProviders(<ProductWindow />);

    act(() => vi.advanceTimersByTime(PREVIEW_STEP_MS / 2));
    fireEvent.click(screen.getByRole('tab', { name: 'Demand Intelligence' }));
    const demand = within(document.querySelector('[data-preview-layer="demand"]') as HTMLElement);

    act(() => vi.advanceTimersByTime(PREVIEW_STEP_MS / 2));
    expect(demand.getByText('Trends')).toHaveAttribute('aria-current', 'page');

    act(() => vi.advanceTimersByTime(PREVIEW_STEP_MS / 2));
    expect(demand.getByText('Mentions & Citations')).toHaveAttribute('aria-current', 'page');
  });

  it('cycles through the shipped AI Visibility views inside Demand Intelligence', () => {
    vi.useFakeTimers();
    renderWithProviders(<ProductWindow />);

    fireEvent.click(screen.getByRole('tab', { name: 'Demand Intelligence' }));
    const panel = document.querySelector('[data-preview-layer="demand"]');
    expect(panel).not.toBeNull();
    const demand = within(panel as HTMLElement);
    expect(demand.getByText('Trends')).toHaveAttribute('aria-current', 'page');
    expect(demand.getByText('Across completed audits')).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(PREVIEW_STEP_MS));
    expect(demand.getByText('Mentions & Citations')).toHaveAttribute('aria-current', 'page');
    expect(demand.getByRole('heading', { name: 'Cited content' })).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(PREVIEW_STEP_MS));
    expect(demand.getByText('Query Fanout')).toHaveAttribute('aria-current', 'page');
    expect(demand.getByRole('heading', { name: 'Query fanout' })).toBeInTheDocument();
  });
});
