import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { promptsApi } from '@/lib/api/prompts';
import { providersApi } from '@/lib/api/providers';
import { queryKeys } from '@/lib/api/query-keys';
import { runsApi } from '@/lib/api/runs';
import { renderWithProviders } from '@/test/render';

import { LaunchDialog } from './launch-dialog';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
const PROMPT_SET_ID = '22222222-2222-4222-8222-222222222222';
const PROMPT_IDS = ['33333333-3333-4333-8333-333333333333', '44444444-4444-4444-8444-444444444444'];

function stubApis() {
  vi.spyOn(promptsApi, 'listPromptSets').mockResolvedValue([
    { id: PROMPT_SET_ID, name: 'Brand portfolio', prompt_count: 7 },
  ] as never);
  vi.spyOn(providersApi, 'listConnections').mockResolvedValue([
    {
      api_key_set: true,
      last_test_status: 'ok',
      routes: [{ logical_engine: 'chatgpt' }],
    },
  ] as never);
  vi.spyOn(runsApi, 'estimateAudit').mockResolvedValue(undefined as never);
  return vi.spyOn(runsApi, 'launchAudit').mockResolvedValue({ id: 'audit' } as never);
}

/** Pick one engine, which is what makes the selection launchable. */
async function selectEngineAndLaunch() {
  fireEvent.click(await screen.findByRole('button', { name: 'ChatGPT' }));
  fireEvent.click(screen.getByRole('button', { name: 'Launch audit' }));
}

describe('LaunchDialog fixed prompt selection', () => {
  afterEach(() => vi.restoreAllMocks());

  it('locks the field and shows the selection the prompt_ids payload uses', async () => {
    // `promptSetLocked` was derived from `fixedPromptSetId` alone, so a
    // `fixedPromptIds` caller kept an editable prompt-set select whose value
    // `buildLaunchPayload` then ignored.
    const launch = stubApis();

    renderWithProviders(
      <LaunchDialog
        open
        onOpenChange={() => undefined}
        projectId={PROJECT_ID}
        fixedPromptIds={PROMPT_IDS}
        auditScope="commerce"
      />,
    );

    expect(await screen.findByText('2 selected prompts')).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    await selectEngineAndLaunch();

    await waitFor(() =>
      expect(launch).toHaveBeenCalledWith({
        project_id: PROJECT_ID,
        prompt_ids: PROMPT_IDS,
        engines: ['chatgpt'],
        repetitions: expect.any(Number),
        audit_scope: 'commerce',
      }),
    );
  });

  it('prefers an explicit selection label over the derived prompt count', async () => {
    const launch = stubApis();

    renderWithProviders(
      <LaunchDialog
        open
        onOpenChange={() => undefined}
        projectId={PROJECT_ID}
        fixedPromptIds={PROMPT_IDS}
        promptSelectionLabel="2 approved prompts for Running shoes"
        auditScope="commerce"
      />,
    );

    expect(await screen.findByText('2 approved prompts for Running shoes')).toBeInTheDocument();
    await selectEngineAndLaunch();

    await waitFor(() =>
      expect(launch).toHaveBeenCalledWith(expect.objectContaining({ prompt_ids: PROMPT_IDS })),
    );
  });

  it('locks a fixed prompt set and launches that same set', async () => {
    const launch = stubApis();

    renderWithProviders(
      <LaunchDialog
        open
        onOpenChange={() => undefined}
        projectId={PROJECT_ID}
        fixedPromptSetId={PROMPT_SET_ID}
        promptSelectionLabel="Commerce Product Visibility"
      />,
    );

    expect(await screen.findByText('Commerce Product Visibility')).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    await selectEngineAndLaunch();

    await waitFor(() =>
      expect(launch).toHaveBeenCalledWith(
        expect.objectContaining({ prompt_set_id: PROMPT_SET_ID, audit_scope: 'brand' }),
      ),
    );
  });
});

describe('LaunchDialog prompt batching', () => {
  afterEach(() => vi.restoreAllMocks());

  /** A set of `count` audit-eligible prompts, in creation order. */
  function setWithPrompts(count: number) {
    return [
      {
        id: PROMPT_SET_ID,
        name: 'Brand portfolio',
        prompt_count: count,
        prompts: Array.from({ length: count }, (_, index) => ({
          id: `prompt-${String(index).padStart(2, '0')}`,
          text: `Prompt ${index}`,
          enabled: true,
          status: 'active',
          created_at: `2026-01-${String(index + 1).padStart(2, '0')}T00:00:00Z`,
        })),
      },
    ];
  }

  it('runs a chosen batch of ten as an explicit prompt id list', async () => {
    // The launch screen used to offer no choice: picking a set ran every
    // prompt in it, however large and however expensive.
    const launch = stubApis();
    vi.spyOn(promptsApi, 'listPromptSets').mockResolvedValue(setWithPrompts(23) as never);

    renderWithProviders(
      <LaunchDialog open onOpenChange={() => undefined} projectId={PROJECT_ID} />,
    );

    const batchSelect = await screen.findByLabelText(/Prompts to run/);
    expect(screen.getByRole('option', { name: 'All 23 prompts' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Prompts 21-23' })).toBeInTheDocument();

    fireEvent.change(batchSelect, { target: { value: '1' } });
    await selectEngineAndLaunch();

    await waitFor(() =>
      expect(launch).toHaveBeenCalledWith(
        expect.objectContaining({
          prompt_ids: Array.from({ length: 10 }, (_, index) => `prompt-${index + 10}`),
        }),
      ),
    );
    expect(launch.mock.calls[0][0]).not.toHaveProperty('prompt_set_id');
  });

  it('runs the whole set by default, and offers no batching below one batch', async () => {
    const launch = stubApis();
    vi.spyOn(promptsApi, 'listPromptSets').mockResolvedValue(setWithPrompts(7) as never);

    renderWithProviders(
      <LaunchDialog open onOpenChange={() => undefined} projectId={PROJECT_ID} />,
    );

    await screen.findByRole('button', { name: 'ChatGPT' });
    // Seven prompts is one batch: "All 7" and "Prompts 1-7" are the same run.
    expect(screen.queryByLabelText(/Prompts to run/)).not.toBeInTheDocument();
    await selectEngineAndLaunch();

    await waitFor(() =>
      expect(launch).toHaveBeenCalledWith(
        expect.objectContaining({ prompt_set_id: PROMPT_SET_ID }),
      ),
    );
  });

  it('does not turn a stale batch selection into a whole-set launch after refresh', async () => {
    const launch = stubApis();
    vi.spyOn(promptsApi, 'listPromptSets').mockResolvedValue(setWithPrompts(23) as never);

    const { queryClient } = renderWithProviders(
      <LaunchDialog open onOpenChange={() => undefined} projectId={PROJECT_ID} />,
    );

    fireEvent.change(await screen.findByLabelText(/Prompts to run/), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: 'ChatGPT' }));
    expect(screen.getByRole('button', { name: 'Launch audit' })).toBeEnabled();

    act(() => {
      queryClient.setQueryData(queryKeys.prompts.sets(PROJECT_ID), setWithPrompts(7));
    });

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Launch audit' })).toBeDisabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Launch audit' }));
    expect(launch).not.toHaveBeenCalled();

    const recoverySelect = screen.getByLabelText(/Prompts to run/);
    expect(screen.getByRole('option', { name: 'All 7 prompts' })).toBeInTheDocument();
    fireEvent.change(recoverySelect, { target: { value: 'all' } });
    expect(screen.getByRole('button', { name: 'Launch audit' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Launch audit' }));
    await waitFor(() =>
      expect(launch).toHaveBeenCalledWith(
        expect.objectContaining({ prompt_set_id: PROMPT_SET_ID }),
      ),
    );
  });
});
