import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Button } from '@/components/ui/button';

import { FlowActions, FlowGroup, FlowShell } from './flow-shell';

const steps = [
  { id: 'brand', label: 'Basics' },
  { id: 'research', label: 'Research' },
  { id: 'confirm', label: 'Confirm' },
] as const;

describe('FlowShell', () => {
  it('labels the main landmark and announces the current setup step once', () => {
    render(
      <FlowShell mainLabel="Project setup" steps={steps} currentStep={1}>
        <h1 className="flow-title">Finding what to track</h1>
      </FlowShell>,
    );

    expect(screen.getByRole('main', { name: 'Project setup' })).toBeVisible();
    const progress = screen.getByRole('navigation', { name: 'Setup progress' });
    const current = within(progress).getByRole('listitem', { current: 'step' });
    expect(current).toHaveTextContent('Research');
    expect(progress.querySelectorAll('[aria-current="step"]')).toHaveLength(1);
  });

  it('collapses the same semantic step list below 640px', () => {
    const { container } = render(
      <FlowShell mainLabel="Project setup" steps={steps} currentStep={2}>
        <p className="website-body">Review the facts.</p>
      </FlowShell>,
    );

    expect(
      container.querySelector('[aria-current="step"] .flow-step-mobile-prefix'),
    ).toHaveTextContent('Step 3 of 3');
    expect(container.querySelector('.flow-progress-rule')).not.toBeNull();
    expect(container.querySelectorAll('.flow-progress ol')).toHaveLength(1);
  });

  it('keeps secondary then primary actions in visual and DOM order', () => {
    render(
      <FlowActions
        secondary={<Button variant="ghost">Back</Button>}
        primary={<Button>Create project</Button>}
      />,
    );

    const actions = screen.getByText('Back').closest('.flow-action-content');
    expect(actions).not.toBeNull();
    const labels = within(actions as HTMLElement)
      .getAllByRole('button')
      .map((button) => button.textContent);
    expect(labels).toEqual(['Back', 'Create project']);
  });

  it('renders one flat ruled group with the flow type roles', () => {
    render(
      <FlowGroup title="Your websites" help="Auto-verified from your domain." meta="1 of 1">
        <span>example.com</span>
      </FlowGroup>,
    );

    expect(screen.getByRole('heading', { name: 'Your websites' })).toHaveClass('flow-group-title');
    expect(screen.getByText('Auto-verified from your domain.')).toHaveClass('flow-help');
    expect(screen.getByText('1 of 1')).toHaveClass('flow-meta');
    expect(screen.getByRole('heading').closest('section')).toHaveClass('flow-group');
  });
});
