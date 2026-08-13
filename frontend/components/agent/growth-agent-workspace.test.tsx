import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { agentApi, type AgentTaskRun } from '@/lib/api/agent';
import { renderWithProviders } from '@/test/render';
import { GrowthAgentWorkspace } from './growth-agent-workspace';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
const RUN_ID = '22222222-2222-4222-8222-222222222222';
const ATTEMPT_ID = '33333333-3333-4333-8333-333333333333';
let searchParams = new URLSearchParams();

vi.mock('next/navigation', () => ({
  useSearchParams: () => searchParams,
}));

vi.mock('@/lib/project/project-context', () => ({
  useProjectContext: () => ({
    activeProject: { id: PROJECT_ID, name: 'Asian School' },
    isLoading: false,
  }),
}));

vi.mock('@/lib/api/agent', async (loadOriginal) => {
  const original = await loadOriginal<typeof import('@/lib/api/agent')>();
  return {
    ...original,
    agentApi: {
      listTasks: vi.fn(),
      getTask: vi.fn(),
      submitTask: vi.fn(),
      cancel: vi.fn(),
    },
  };
});

function run(status = 'running'): AgentTaskRun {
  return {
    id: RUN_ID,
    project_id: PROJECT_ID,
    task_type: 'build_roadmap',
    objective: 'Build an admissions roadmap',
    task_policy_version: 'growth-agent-v2',
    status,
    result: null,
    provider_adapter: '',
    endpoint_host: '',
    model: '',
    instruction_version: 'v2',
    usage: null,
    latency_ms: null,
    error_code: '',
    error_detail: '',
    attempt_count: 1,
    completed_at: null,
    cancelled_at: null,
    created_at: '2026-08-09T00:00:00Z',
    updated_at: '2026-08-09T00:00:00Z',
    attempts: [
      {
        id: ATTEMPT_ID,
        run_attempt: 1,
        ordinal: 1,
        tool_name: 'opportunities.read_ranked',
        tool_version: '2.0.0',
        status: 'completed',
        input: { project_id: PROJECT_ID },
        artifact_refs: [{ kind: 'opportunity', id: '44444444-4444-4444-8444-444444444444' }],
        output_hash: 'evidence-output-hash',
        omissions: [{ reason: 'roadmap_item_limit', count: 2 }],
        error_code: '',
        retryable: false,
        latency_ms: 7,
        created_at: '2026-08-09T00:00:01Z',
      },
    ],
  };
}

describe('GrowthAgentWorkspace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    searchParams = new URLSearchParams();
    vi.mocked(agentApi.listTasks).mockResolvedValue([run()]);
    vi.mocked(agentApi.getTask).mockResolvedValue(run());
    vi.mocked(agentApi.submitTask).mockResolvedValue(run('queued'));
    vi.mocked(agentApi.cancel).mockResolvedValue(run('cancelled'));
  });

  it('renders standalone task history and bounded task controls', async () => {
    renderWithProviders(<GrowthAgentWorkspace />);

    expect(
      await screen.findByRole('heading', { name: 'Build an admissions roadmap' }),
    ).toBeVisible();
    expect(screen.getByText('Read-only project evidence')).toBeVisible();
    expect(screen.getByRole('combobox', { name: 'Task' })).toHaveValue('explain');
    expect(screen.getByRole('textbox', { name: /Objective/ })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Start task' })).toBeDisabled();
    expect(screen.queryByText(/conversation/i)).not.toBeInTheDocument();
  });

  it('keeps the cached run visible while its detail query loads', async () => {
    vi.mocked(agentApi.getTask).mockImplementation(
      () =>
        new Promise<AgentTaskRun>(() => {
          // Keep the detail query pending to exercise the cached list projection.
        }),
    );
    renderWithProviders(<GrowthAgentWorkspace />);

    expect(
      await screen.findByRole('heading', { name: 'Build an admissions roadmap' }),
    ).toBeVisible();
    expect(screen.queryByText('Loading task…')).not.toBeInTheDocument();
  });

  it('keeps the cached run visible when its detail refresh fails', async () => {
    vi.mocked(agentApi.getTask).mockRejectedValueOnce(new Error('refresh failed'));
    renderWithProviders(<GrowthAgentWorkspace />);

    expect(
      await screen.findByRole('heading', { name: 'Build an admissions roadmap' }),
    ).toBeVisible();
    expect(
      screen.queryByText('The task could not be loaded. Refresh and try again.'),
    ).not.toBeInTheDocument();
  });

  it('submits only a fixed task type, objective, and project', async () => {
    const user = userEvent.setup();
    renderWithProviders(<GrowthAgentWorkspace />);

    await user.selectOptions(screen.getByRole('combobox', { name: 'Task' }), 'build_roadmap');
    await user.type(screen.getByRole('textbox', { name: /Objective/ }), 'Prioritize admissions');
    await user.click(screen.getByRole('button', { name: 'Start task' }));

    await waitFor(() =>
      expect(agentApi.submitTask).toHaveBeenCalledWith(
        {
          project_id: PROJECT_ID,
          task_type: 'build_roadmap',
          objective: 'Prioritize admissions',
        },
        expect.any(String),
      ),
    );
  });

  it('uses supported query parameters without accepting removed task types', async () => {
    searchParams = new URLSearchParams({
      task: 'build_roadmap',
      objective: 'Build from current Site evidence',
    });
    const view = renderWithProviders(<GrowthAgentWorkspace />);

    expect(await screen.findByRole('combobox', { name: 'Task' })).toHaveValue('build_roadmap');
    expect(screen.getByRole('textbox', { name: /Objective/ })).toHaveValue(
      'Build from current Site evidence',
    );

    searchParams = new URLSearchParams({ task: 'create_brief', objective: 'Removed workflow' });
    view.rerender(<GrowthAgentWorkspace />);
    expect(screen.getByRole('combobox', { name: 'Task' })).toHaveValue('explain');
    expect(screen.getByRole('textbox', { name: /Objective/ })).toHaveValue('Removed workflow');
  });

  it('shows the result and limitations without conversation scaffolding', async () => {
    const completed = run('completed');
    completed.result = {
      answer: 'Admissions pages are the highest-priority work.',
      limitations: ['Demand evidence is unavailable.'],
      artifact_refs: completed.attempts[0]!.artifact_refs,
    };
    vi.mocked(agentApi.listTasks).mockResolvedValue([completed]);
    vi.mocked(agentApi.getTask).mockResolvedValue(completed);

    renderWithProviders(<GrowthAgentWorkspace />);

    expect(
      await screen.findByText('Admissions pages are the highest-priority work.'),
    ).toBeVisible();
    expect(screen.getByText('Demand evidence is unavailable.')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument();
  });

  it('exposes immutable evidence attempt metadata on demand', async () => {
    const user = userEvent.setup();
    renderWithProviders(<GrowthAgentWorkspace />);

    const attempt = await screen.findByText('opportunities.read_ranked');
    await user.click(attempt);
    const evidence = attempt.closest('details');
    expect(evidence).not.toBeNull();
    expect(within(evidence!).getByText('Authorized input')).toBeVisible();
    expect(within(evidence!).getByText(/opportunity: 44444444/)).toBeVisible();
    expect(within(evidence!).getByText(/evidence-output-hash/)).toBeVisible();
    expect(within(evidence!).getByText(/roadmap_item_limit/)).toBeVisible();
  });

  it('cancels an active task and surfaces cancellation failures', async () => {
    const user = userEvent.setup();
    vi.mocked(agentApi.cancel).mockRejectedValueOnce(new Error('The task could not be cancelled.'));
    renderWithProviders(<GrowthAgentWorkspace />);

    await user.click(await screen.findByRole('button', { name: 'Cancel' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('The task could not be cancelled.');
    expect(agentApi.cancel).toHaveBeenCalledWith(PROJECT_ID, RUN_ID);
  });

  it('does not clear an objective submission error after cancellation succeeds', async () => {
    const user = userEvent.setup();
    vi.mocked(agentApi.submitTask).mockRejectedValueOnce(
      new Error('The task could not be started.'),
    );
    renderWithProviders(<GrowthAgentWorkspace />);

    await user.type(screen.getByRole('textbox', { name: /Objective/ }), 'Explain evidence');
    await user.click(screen.getByRole('button', { name: 'Start task' }));
    expect(await screen.findByText('The task could not be started.')).toHaveAttribute(
      'role',
      'alert',
    );

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(agentApi.cancel).toHaveBeenCalledWith(PROJECT_ID, RUN_ID));
    expect(screen.getByText('The task could not be started.')).toBeVisible();
  });
});
