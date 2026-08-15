import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import type { BrandProfile } from '@/lib/api/types';
import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';

import { BrandProfilePanel } from './brand-profile-panel';

const projectId = '55555555-5555-4555-8555-555555555555';

const profile: BrandProfile = {
  id: '11111111-1111-4111-8111-111111111111',
  workspace_id: '66666666-6666-4666-8666-666666666666',
  project_id: projectId,
  brand_id: '22222222-2222-4222-8222-222222222222',
  description: '',
  positioning: '',
  products_services: [],
  target_audience: '',
  sources: {
    description: null,
    positioning: null,
    products_services: null,
    target_audience: null,
  },
  source_artifact_ids: {
    description: null,
    positioning: null,
    products_services: null,
    target_audience: null,
  },
  created_at: '2026-07-21T00:00:00Z',
  updated_at: '2026-07-21T00:00:00Z',
};

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

describe('BrandProfilePanel', () => {
  it('saves direct edits as manual knowledge', async () => {
    const user = userEvent.setup({ delay: null });
    let requestBody: unknown;
    mswServer.use(
      http.put(`/api/v1/projects/${projectId}/brand-profile`, async ({ request }) => {
        requestBody = await request.json();
        return HttpResponse.json({
          ...profile,
          description: 'A value-focused family retailer.',
          sources: {
            ...profile.sources,
            description: {
              origin: 'manual',
              review_state: 'confirmed',
              reviewed_by: null,
              reviewed_at: null,
            },
          },
        });
      }),
    );

    renderWithProviders(<BrandProfilePanel projectId={projectId} profile={profile} />);
    await user.type(screen.getByLabelText('Description'), 'A value-focused family retailer.');
    await user.type(screen.getByLabelText('Products and services'), 'Clothing,');
    expect(screen.getByLabelText('Products and services')).toHaveValue('Clothing,');
    await user.click(screen.getByRole('button', { name: /save brand knowledge/i }));

    expect(await screen.findByText(/brand knowledge saved/i)).toBeInTheDocument();
    expect(requestBody).toMatchObject({
      description: 'A value-focused family retailer.',
      products_services: ['Clothing'],
    });
  });

  it('locks profile fields while a save is pending', async () => {
    const user = userEvent.setup({ delay: null });
    let finishSave: (() => void) | undefined;
    mswServer.use(
      http.put(`/api/v1/projects/${projectId}/brand-profile`, async () => {
        await new Promise<void>((resolve) => {
          finishSave = resolve;
        });
        return HttpResponse.json({ ...profile, description: 'Submitted description.' });
      }),
    );

    renderWithProviders(<BrandProfilePanel projectId={projectId} profile={profile} />);
    const description = screen.getByLabelText('Description');
    await user.type(description, 'Submitted description.');
    await user.click(screen.getByRole('button', { name: /save brand knowledge/i }));

    await waitFor(() => expect(description).toBeDisabled());
    expect(screen.getByLabelText('Positioning')).toBeDisabled();
    expect(screen.getByLabelText('Products and services')).toBeDisabled();
    finishSave?.();
    expect(await screen.findByText(/brand knowledge saved/i)).toBeInTheDocument();
  });
});
