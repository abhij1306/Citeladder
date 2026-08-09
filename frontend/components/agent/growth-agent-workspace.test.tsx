import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/render';
import { agentApi, type AgentTaskRun } from '@/lib/api/agent';
import { GrowthAgentWorkspace } from './growth-agent-workspace';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
const RUN_ID = '22222222-2222-4222-8222-222222222222';
const STEP_ID = '33333333-3333-4333-8333-333333333333';
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
      capabilities: vi.fn(),
      listTasks: vi.fn(),
      submitTask: vi.fn(),
      decide: vi.fn(),
      cancel: vi.fn(),
    },
  };
});

function run(status = 'awaiting_user'): AgentTaskRun {
  return {
    id: RUN_ID,
    project_id: PROJECT_ID,
    conversation_id: null,
    parent_run_id: null,
    context_package_id: null,
    task_type: 'generate_draft',
    objective: 'Generate an admissions FAQ draft',
    requested_outputs: [],
    task_policy_version: 'growth-agent-v1',
    allowed_tools: ['content.generate_draft'],
    resource_scope: {},
    industry_pack_id: 'education',
    industry_pack_version: '1',
    status,
    plan: [],
    result: {
      decisions_remaining: ['save_content'],
      next_step: 'Review the generated draft.',
      citations: ['44444444-4444-4444-8444-444444444444'],
      artifacts_created: [
        { kind: 'content_generation', id: '55555555-5555-4555-8555-555555555555' },
      ],
    },
    validation: null,
    decisions: [],
    provider_adapter: 'deterministic',
    endpoint_host: '',
    model: 'bounded-projection-v1',
    capability_snapshot: {},
    instruction_version: 'v1',
    skill_version: 'v1',
    usage: null,
    latency_ms: null,
    error_code: '',
    error_detail: '',
    completed_at: null,
    cancelled_at: null,
    created_at: '2026-08-09T00:00:00Z',
    updated_at: '2026-08-09T00:00:00Z',
    steps: [
      {
        id: STEP_ID,
        ordinal: 1,
        name: 'Queue brief-driven content generation.',
        tool_name: 'content.generate_draft',
        tool_version: '1.0.0',
        tool_kind: 'save_content',
        status,
        input: {},
        output: null,
        child_task_kind: '',
        child_task_id: null,
        retry_count: 0,
        error_code: '',
        error_detail: '',
        started_at: null,
        completed_at: null,
      },
    ],
    context: null,
  };
}

describe('GrowthAgentWorkspace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    searchParams = new URLSearchParams();
    vi.mocked(agentApi.capabilities).mockResolvedValue({
      configured: false,
      provider_adapter: '',
      endpoint_host: '',
      model: '',
      model_capabilities: {},
      policy_version: 'v1',
      context_policy_version: 'v1',
      tool_registry_version: 'v1',
      task_catalog: [
        {
          task_type: 'build_roadmap',
          title: 'Build roadmap',
          description: 'Build it',
          allowed_tools: [],
          required_scope: [],
          requested_outputs: [],
          max_steps: 8,
          max_tool_calls: 8,
        },
      ],
      tool_catalog: [],
    });
    vi.mocked(agentApi.listTasks).mockResolvedValue([run()]);
    vi.mocked(agentApi.submitTask).mockResolvedValue(run('completed'));
    vi.mocked(agentApi.decide).mockResolvedValue(run('awaiting_task'));
    vi.mocked(agentApi.cancel).mockResolvedValue(run('cancelled'));
  });

  it('shows bounded progress, provider state, and the save-content decision', async () => {
    const user = userEvent.setup();
    renderWithProviders(<GrowthAgentWorkspace />);

    expect(await screen.findByText('Generate an admissions FAQ draft')).toBeInTheDocument();
    expect(screen.getByText(/Deterministic mode/)).toBeInTheDocument();
    expect(screen.getByText('Your decision is required')).toBeInTheDocument();
    expect(screen.getByText('Review the generated draft.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /content generation/i })).toHaveAttribute(
      'href',
      '/content',
    );

    await user.click(screen.getByRole('button', { name: 'Review decision' }));
    expect(screen.getByRole('dialog', { name: 'Save this content?' })).toBeInTheDocument();
    expect(screen.getByText(/does not publish the draft/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(agentApi.decide).toHaveBeenCalledWith(PROJECT_ID, RUN_ID, 'save_content', true),
    );
  });

  it('records an explicit decline separately from dismissing the dialog', async () => {
    const user = userEvent.setup();
    renderWithProviders(<GrowthAgentWorkspace />);

    await user.click(await screen.findByRole('button', { name: 'Review decision' }));
    await user.click(screen.getByRole('button', { name: "Don't save" }));

    await waitFor(() =>
      expect(agentApi.decide).toHaveBeenCalledWith(PROJECT_ID, RUN_ID, 'save_content', false),
    );
  });

  it('keeps a failed decision open and explains that it was not applied', async () => {
    const user = userEvent.setup();
    vi.mocked(agentApi.decide).mockRejectedValue(new Error('Decision was not recorded.'));
    renderWithProviders(<GrowthAgentWorkspace />);

    await user.click(await screen.findByRole('button', { name: 'Review decision' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Decision was not recorded.')).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'Save this content?' })).toBeInTheDocument();
  });

  it('reports cancellation failures and permits a retry', async () => {
    const user = userEvent.setup();
    vi.mocked(agentApi.cancel).mockRejectedValue(new Error('Cancellation failed.'));
    renderWithProviders(<GrowthAgentWorkspace />);

    const button = await screen.findByRole('button', { name: 'Cancel task' });
    await user.click(button);

    expect(await screen.findByRole('alert')).toHaveTextContent('Cancellation failed.');
    expect(button).toBeEnabled();
  });

  it('falls back from an invalid deep-linked task to the capability catalog', async () => {
    const user = userEvent.setup();
    searchParams = new URLSearchParams({ task: 'not-a-task' });
    renderWithProviders(<GrowthAgentWorkspace />);

    const select = await screen.findByRole('combobox', { name: 'Supported task' });
    await waitFor(() => expect(select).toHaveValue('build_roadmap'));
    await user.click(screen.getByRole('button', { name: 'Start task' }));

    await waitFor(() =>
      expect(agentApi.submitTask).toHaveBeenCalledWith(
        expect.objectContaining({ task_type: 'build_roadmap' }),
        expect.any(String),
      ),
    );
  });

  it('distinguishes capability and history failures from empty states', async () => {
    vi.mocked(agentApi.capabilities).mockRejectedValue(new Error('capabilities failed'));
    vi.mocked(agentApi.listTasks).mockRejectedValue(new Error('history failed'));
    renderWithProviders(<GrowthAgentWorkspace />);

    expect(
      await screen.findByText('Agent capabilities could not be loaded.', undefined, {
        timeout: 5000,
      }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText('Task history could not be loaded.', undefined, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/No runs yet/)).not.toBeInTheDocument();
  });
});
