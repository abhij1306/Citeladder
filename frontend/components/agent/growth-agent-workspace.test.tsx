import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { agentApi, type AgentTaskRun } from '@/lib/api/agent';
import { renderWithProviders } from '@/test/render';
import { GrowthAgentWorkspace } from './growth-agent-workspace';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
const RUN_ID = '22222222-2222-4222-8222-222222222222';
vi.mock('@/lib/project/project-context', () => ({
  useProjectContext: () => ({
    activeProject: { id: PROJECT_ID, name: 'Asian School' },
    isLoading: false,
  }),
}));
vi.mock('@/lib/api/agent', async (loadOriginal) => ({
  ...(await loadOriginal<typeof import('@/lib/api/agent')>()),
  agentApi: { listTasks: vi.fn(), getTask: vi.fn(), submitTask: vi.fn(), cancel: vi.fn() },
}));

function run(status = 'running'): AgentTaskRun {
  return {
    id: RUN_ID,
    project_id: PROJECT_ID,
    task_type: 'build_roadmap',
    objective: 'Build an admissions roadmap',
    status,
    result: null,
    error_code: '',
    error_detail: '',
    attempt_count: 1,
    completed_at: null,
    cancelled_at: null,
    created_at: '2026-08-09T00:00:00Z',
    updated_at: '2026-08-09T00:00:00Z',
  };
}

describe('GrowthAgentWorkspace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(agentApi.listTasks).mockResolvedValue([run()]);
    vi.mocked(agentApi.getTask).mockResolvedValue(run());
    vi.mocked(agentApi.submitTask).mockResolvedValue(run('queued'));
    vi.mocked(agentApi.cancel).mockResolvedValue(run('cancelled'));
  });

  it('offers exactly the two plain-language bounded tasks', async () => {
    const user = userEvent.setup();
    renderWithProviders(<GrowthAgentWorkspace />);
    expect(
      await screen.findByRole('heading', { name: 'Build an admissions roadmap' }),
    ).toBeVisible();
    await user.click(screen.getByRole('combobox', { name: 'Task' }));
    expect(screen.getByRole('option', { name: 'Explain my latest data' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Prioritize next steps' })).toBeInTheDocument();
    expect(screen.queryByText(/conversation/i)).not.toBeInTheDocument();
  });

  it('submits only the fixed task, objective, and selected project', async () => {
    const user = userEvent.setup();
    renderWithProviders(<GrowthAgentWorkspace />);
    await user.click(screen.getByRole('combobox', { name: 'Task' }));
    await user.click(screen.getByRole('option', { name: 'Prioritize next steps' }));
    await user.type(screen.getByRole('textbox', { name: /Objective/ }), 'Prioritize admissions');
    await user.click(screen.getByRole('button', { name: 'Start task' }));
    await waitFor(() =>
      expect(agentApi.submitTask).toHaveBeenCalledWith(
        { project_id: PROJECT_ID, task_type: 'build_roadmap', objective: 'Prioritize admissions' },
        expect.any(String),
      ),
    );
  });

  it('renders summary, observations, and persisted-order next steps', async () => {
    const completed = run('completed');
    completed.result = {
      summary: 'Admissions pages are the highest-priority work.',
      observations: ['Search Demand has one high-impression, low-click query.'],
      roadmap_items: [
        {
          rank: 1,
          title: 'Improve admissions pages',
          remediation: 'Answer common admissions questions clearly.',
          target_url: 'https://example.com/admissions',
          priority_score: 90,
          severity: 'high',
        },
      ],
      sources: [
        {
          key: 'search_demand',
          label: 'Search Demand',
          availability: 'available',
          window: { start: '2026-08-01', end: '2026-08-07' },
          coverage: null,
          reason: null,
        },
      ],
      limitations: ['Demand evidence is unavailable.'],
      artifact_refs: [{ kind: 'opportunity', id: '44444444-4444-4444-8444-444444444444' }],
    };
    vi.mocked(agentApi.listTasks).mockResolvedValue([completed]);
    vi.mocked(agentApi.getTask).mockResolvedValue(completed);
    renderWithProviders(<GrowthAgentWorkspace />);
    expect(await screen.findByText('Summary')).toBeVisible();
    expect(screen.getByText('What the data shows')).toBeVisible();
    expect(screen.getByText('Prioritized next steps')).toBeVisible();
    expect(screen.getByText('Improve admissions pages')).toBeVisible();
    expect(screen.getByText('Demand evidence is unavailable.')).toBeVisible();
  });

  it('keeps Data used useful without exposing raw attempts, identifiers, hashes, or JSON', async () => {
    const user = userEvent.setup();
    const completed = run('completed');
    completed.result = {
      summary: 'Saved data is ready to explain.',
      observations: [],
      roadmap_items: [],
      limitations: [],
      sources: [
        {
          key: 'site_health',
          label: 'Site Health',
          availability: 'unavailable',
          window: null,
          coverage: null,
          reason: 'No Site Health snapshot is available yet.',
        },
      ],
      artifact_refs: [{ kind: 'site_snapshot', id: '44444444-4444-4444-8444-444444444444' }],
    };
    vi.mocked(agentApi.listTasks).mockResolvedValue([completed]);
    vi.mocked(agentApi.getTask).mockResolvedValue(completed);
    renderWithProviders(<GrowthAgentWorkspace />);
    const disclosure = await screen.findByText('Data used');
    const internals = [
      'opportunities.read_ranked',
      'evidence-output-hash',
      '2.0.0',
      '44444444-4444-4444-8444-444444444444',
      '{"project_id"',
    ];
    internals.forEach((value) => expect(document.body).not.toHaveTextContent(value));
    await user.click(disclosure);
    expect(screen.getByText('Site Health')).toBeVisible();
    expect(screen.getByText('unavailable')).toBeVisible();
    expect(screen.getByText('1 saved data artifact supported this result.')).toBeVisible();
    internals.forEach((value) => expect(document.body).not.toHaveTextContent(value));
  });
});
