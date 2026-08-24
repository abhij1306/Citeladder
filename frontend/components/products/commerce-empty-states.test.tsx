import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';

import { AiVisibilityPanel } from './ai-visibility-panel';
import { CommerceOverviewPanel } from './commerce-overview-panel';

const missingVisibility = {
  isLoading: false,
  isError: true,
  error: new ApiError('No completed audit with product metrics', 404, '{}'),
  data: undefined,
};

describe('Commerce first-run states', () => {
  it('sends an empty catalog to the Catalog tab instead of showing a load failure', async () => {
    const user = userEvent.setup();
    const onSelectTab = vi.fn();

    render(
      <CommerceOverviewPanel
        queries={
          {
            productsQuery: { isLoading: false, isError: false, data: [] },
            visibilityQuery: missingVisibility,
            opportunitiesQuery: { data: undefined },
          } as never
        }
        onSelectTab={onSelectTab}
        onLaunchAudit={vi.fn()}
      />,
    );

    expect(
      screen.getByRole('heading', { name: 'Add products before measuring Commerce visibility' }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Import CSV' }));
    expect(onSelectTab).toHaveBeenCalledWith('catalog');
  });

  it('treats a missing product audit as a launchable first-run state', async () => {
    const user = userEvent.setup();
    const onLaunchAudit = vi.fn();

    render(
      <AiVisibilityPanel
        projectId="11111111-1111-4111-8111-111111111111"
        queries={
          {
            productsQuery: { isLoading: false, isError: false, data: [{ id: 'product-1' }] },
            visibilityQuery: missingVisibility,
          } as never
        }
        onAddProducts={vi.fn()}
        onLaunchAudit={onLaunchAudit}
      />,
    );

    expect(
      screen.getByRole('heading', { name: 'No Commerce visibility audit yet' }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Launch audit' }));
    expect(onLaunchAudit).toHaveBeenCalledOnce();
  });

  it('keeps real Commerce API failures distinct from first-run absence', () => {
    render(
      <CommerceOverviewPanel
        queries={
          {
            productsQuery: {
              isLoading: false,
              isError: false,
              data: [{ id: 'product-1', attributes: { category: 'Books' } }],
            },
            visibilityQuery: {
              ...missingVisibility,
              error: new ApiError('Server error', 500, '{}'),
            },
            opportunitiesQuery: { data: undefined },
            missingCategorySkus: [],
            categories: ['Books'],
            topicsQuery: { data: [{ id: 'topic-books', name: 'Books' }] },
            commercePromptSet: {
              prompts: [
                {
                  id: 'prompt-discovery',
                  topic_id: 'topic-books',
                  cohort: 'commerce',
                  status: 'active',
                  intent: 'discovery',
                },
                {
                  id: 'prompt-comparison',
                  topic_id: 'topic-books',
                  cohort: 'commerce',
                  status: 'active',
                  intent: 'comparison',
                },
              ],
            },
            commerceAudits: [],
          } as never
        }
        onSelectTab={vi.fn()}
        onLaunchAudit={vi.fn()}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Could not load the Commerce overview.');
  });
});
