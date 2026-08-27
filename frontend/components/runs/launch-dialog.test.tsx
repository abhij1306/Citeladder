import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { promptsApi } from '@/lib/api/prompts';
import { providersApi } from '@/lib/api/providers';
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
  fireEvent.click(await screen.findByRole('checkbox', { name: 'ChatGPT' }));
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
