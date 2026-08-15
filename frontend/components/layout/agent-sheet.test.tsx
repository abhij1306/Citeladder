import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AgentLauncher, AgentSheet } from './agent-sheet';

let activeProject = {
  id: '11111111-1111-4111-8111-111111111111',
  workspace_id: '22222222-2222-4222-8222-222222222222',
};

vi.mock('next/navigation', () => ({
  usePathname: () => '/site',
  useSearchParams: () => new URLSearchParams('start=2026-08-01&end=2026-08-15&tab=pages'),
}));
vi.mock('@/lib/project/project-context', () => ({
  useProjectContext: () => ({ activeProject }),
}));
vi.mock('@/components/agent/growth-agent-workspace', () => ({
  GrowthAgentWorkspace: (props: unknown) => <pre>{JSON.stringify(props)}</pre>,
}));

describe('AgentSheet', () => {
  it('opens from the top bar with bounded typed route context and returns focus', async () => {
    const user = userEvent.setup();
    render(<AgentSheet />);
    const trigger = screen.getByRole('button', { name: 'Agent' });
    await user.click(trigger);
    expect(screen.getByRole('dialog', { name: 'Growth Agent' })).toBeVisible();
    expect(screen.getByText(/"canonicalRoute":"\/site"/)).toBeVisible();
    expect(screen.getByText(/"dateRange":\{"start":"2026-08-01","end":"2026-08-15"\}/)).toBeVisible();
    expect(screen.getByText(/"filters":\{"tab":\["pages"\]\}/)).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Close Growth Agent' }));
    expect(trigger).toHaveFocus();
  });

  it('opens from a contextual launcher with a typed preset', async () => {
    const user = userEvent.setup();
    render(
      <>
        <AgentSheet />
        <AgentLauncher taskType="build_roadmap" objective="Prioritize Website evidence">
          Build roadmap
        </AgentLauncher>
      </>,
    );
    await user.click(screen.getByRole('button', { name: 'Build roadmap' }));
    expect(screen.getByText(/"initialTask":"build_roadmap"/)).toBeVisible();
    expect(screen.getByText(/"initialObjective":"Prioritize Website evidence"/)).toBeVisible();
  });

  it('closes and clears route context when the active project changes', async () => {
    const user = userEvent.setup();
    const view = render(<AgentSheet />);
    await user.click(screen.getByRole('button', { name: 'Agent' }));
    expect(screen.getByRole('dialog', { name: 'Growth Agent' })).toBeVisible();
    activeProject = {
      id: '33333333-3333-4333-8333-333333333333',
      workspace_id: '44444444-4444-4444-8444-444444444444',
    };
    view.rerender(<AgentSheet />);
    expect(screen.queryByRole('dialog', { name: 'Growth Agent' })).not.toBeInTheDocument();
  });
});
