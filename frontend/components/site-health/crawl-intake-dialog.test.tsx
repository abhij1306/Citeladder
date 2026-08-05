import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/render';
import { CrawlIntakeDialog } from './crawl-intake-dialog';

const PROJECT = '11111111-1111-4111-8111-111111111111';

describe('CrawlIntakeDialog', () => {
  it('only starts advanced crawls with a positive safe integer budget', async () => {
    const user = userEvent.setup();
    const onStart = vi.fn();
    renderWithProviders(
      <CrawlIntakeDialog
        projectId={PROJECT}
        open
        advancedControlsEnabled
        onClose={vi.fn()}
        onStart={onStart}
      />,
    );

    const budget = screen.getByRole('spinbutton', { name: 'Page budget' });
    const start = screen.getByRole('button', { name: 'Start crawl' });

    for (const invalid of ['', '0', '-1', '1.5', '9007199254740992']) {
      await user.clear(budget);
      if (invalid) await user.type(budget, invalid);
      expect(start).toBeDisabled();
    }

    await user.clear(budget);
    await user.type(budget, '2');
    expect(start).toBeEnabled();
    await user.click(start);

    expect(onStart).toHaveBeenCalledWith(
      expect.objectContaining({ project_id: PROJECT, discovery_count: 2 }),
    );
  });
});
