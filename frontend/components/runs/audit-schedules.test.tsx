import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { runsApi } from '@/lib/api/runs';
import { renderWithProviders } from '@/test/render';

import { AuditSchedules } from './audit-schedules';

vi.mock('@/lib/api/runs', () => ({
  runsApi: {
    listSchedules: vi.fn(),
    createSchedule: vi.fn(),
  },
}));

const createSchedule = vi.mocked(runsApi.createSchedule);
const listSchedules = vi.mocked(runsApi.listSchedules);

describe('AuditSchedules', () => {
  beforeEach(() => {
    createSchedule.mockReset();
    listSchedules.mockReset();
    listSchedules.mockResolvedValue([]);
    createSchedule.mockResolvedValue(null as never);
  });

  it('preserves the schedule payload while shared controls own its inputs', async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AuditSchedules
        projectId="11111111-1111-4111-8111-111111111111"
        promptSets={[{ id: '22222222-2222-4222-8222-222222222222', name: 'Core prompts' } as never]}
      />,
    );

    await user.click(screen.getByRole('combobox', { name: 'Cadence' }));
    await user.click(screen.getByRole('option', { name: 'Every N minutes' }));
    await user.clear(screen.getByLabelText('Minutes'));
    await user.type(screen.getByLabelText('Minutes'), '15');
    await user.click(screen.getByRole('checkbox', { name: 'gemini' }));
    await user.click(screen.getByRole('button', { name: 'Schedule audit' }));

    await waitFor(() =>
      expect(createSchedule).toHaveBeenCalledWith(
        '11111111-1111-4111-8111-111111111111',
        expect.objectContaining({
          prompt_set_id: '22222222-2222-4222-8222-222222222222',
          audit_scope: 'brand',
          cadence: 'every_n_minutes',
          interval_minutes: 15,
          engines: ['chatgpt', 'gemini'],
        }),
      ),
    );
  });
});
