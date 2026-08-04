import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { getActiveWorkspaceId, setActiveWorkspaceId } from '@/lib/api/client';
import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';

import { ProjectProvider, useProjectContext } from './project-context';

const WORKSPACE_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const PROJECT_1 = '11111111-1111-4111-8111-111111111111';
const PROJECT_2 = '22222222-2222-4222-8222-222222222222';

function project(id: string, name: string, workspaceId = WORKSPACE_A) {
  return {
    id,
    workspace_id: workspaceId,
    name,
    brand_name: name,
    website_url: 'https://example.com',
    country_code: 'US',
    language_code: 'en',
    benchmark_mode: 'consumer_like',
    default_repetitions: 3,
    brand: { aliases: [] },
    owned_domains: [],
    unintended_domains: [],
    competitors: [],
    prompt_sets: [],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

function Harness() {
  const { activeProject, activeProjectId, projects, setActiveProjectId } = useProjectContext();
  return (
    <div>
      <div data-testid="active">{activeProject?.name ?? 'none'}</div>
      <div data-testid="active-id">{activeProjectId ?? 'none'}</div>
      <div data-testid="count">{projects.length}</div>
      {projects.map((p) => (
        <button key={p.id} type="button" onClick={() => setActiveProjectId(p.id)}>
          select {p.name}
        </button>
      ))}
    </div>
  );
}

/** Selects an id that is not in the currently-loaded list (the onboarding case). */
function SelectUnknownHarness() {
  const { activeProject, activeProjectId, projects, setActiveProjectId } = useProjectContext();
  return (
    <div>
      <div data-testid="active">{activeProject?.name ?? 'none'}</div>
      <div data-testid="active-id">{activeProjectId ?? 'none'}</div>
      <div data-testid="count">{projects.length}</div>
      <button type="button" onClick={() => setActiveProjectId(PROJECT_2)}>
        select unknown
      </button>
    </div>
  );
}

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
beforeEach(() => {
  window.localStorage.clear();
  setActiveWorkspaceId(null);
  // The provider backfills logos for any project without one, which every
  // fixture here is. Tests that assert on the backfill override this.
  mswServer.use(
    http.post('/api/v1/projects/:id/logos/refresh', ({ params }) =>
      HttpResponse.json(project(String(params.id), 'Acme')),
    ),
  );
});
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

describe('ProjectProvider', () => {
  it('auto-selects the first project and stamps the workspace header', async () => {
    mswServer.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json([project(PROJECT_1, 'Acme'), project(PROJECT_2, 'Globex')]),
      ),
    );

    renderWithProviders(
      <ProjectProvider>
        <Harness />
      </ProjectProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('Acme'));
    expect(screen.getByTestId('active-id')).toHaveTextContent(PROJECT_1);
    expect(getActiveWorkspaceId()).toBe(WORKSPACE_A);
  });

  it('changes the active project on selection and persists it', async () => {
    mswServer.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json([project(PROJECT_1, 'Acme'), project(PROJECT_2, 'Globex')]),
      ),
    );

    renderWithProviders(
      <ProjectProvider>
        <Harness />
      </ProjectProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('Acme'));

    await userEvent.click(screen.getByRole('button', { name: 'select Globex' }));

    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('Globex'));
    expect(screen.getByTestId('active-id')).toHaveTextContent(PROJECT_2);
    expect(window.localStorage.getItem('citeladder.active-project-id')).toBe(PROJECT_2);
  });

  it('restores a persisted selection when it still exists', async () => {
    window.localStorage.setItem('citeladder.active-project-id', PROJECT_2);
    mswServer.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json([project(PROJECT_1, 'Acme'), project(PROJECT_2, 'Globex')]),
      ),
    );

    renderWithProviders(
      <ProjectProvider>
        <Harness />
      </ProjectProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('Globex'));
  });

  it('keeps a selection made before the new project appears in the list', async () => {
    // Onboarding calls setActiveProjectId(newId) while the provider is still
    // holding the pre-create list, then invalidates. The selection must survive
    // that gap instead of being reset to projects[0].
    let includeNew = false;
    mswServer.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json(
          includeNew
            ? [project(PROJECT_1, 'Acme'), project(PROJECT_2, 'Globex')]
            : [project(PROJECT_1, 'Acme')],
        ),
      ),
    );

    renderWithProviders(
      <ProjectProvider>
        <SelectUnknownHarness />
      </ProjectProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('Acme'));

    // Select the not-yet-listed project. The provider must not stomp it back to
    // projects[0] just because the list has not caught up yet.
    await userEvent.click(screen.getByRole('button', { name: 'select unknown' }));
    includeNew = true;

    await waitFor(() =>
      expect(window.localStorage.getItem('citeladder.active-project-id')).toBe(PROJECT_2),
    );
  });

  it('backfills logos for projects that have none, then re-reads the list once', async () => {
    const refreshed: string[] = [];
    let listCalls = 0;
    mswServer.use(
      http.get('/api/v1/projects', () => {
        listCalls += 1;
        const withLogo = {
          ...project(PROJECT_1, 'Acme'),
          brand: { aliases: [], logo_url: `/api/v1/projects/${PROJECT_1}/logo` },
        };
        // First read has no logo; once the refresh lands, the list carries one.
        return HttpResponse.json([refreshed.length > 0 ? withLogo : project(PROJECT_1, 'Acme')]);
      }),
      http.post('/api/v1/projects/:id/logos/refresh', ({ params }) => {
        refreshed.push(String(params.id));
        return HttpResponse.json({
          ...project(PROJECT_1, 'Acme'),
          brand: { aliases: [], logo_url: `/api/v1/projects/${PROJECT_1}/logo` },
        });
      }),
    );

    renderWithProviders(
      <ProjectProvider>
        <Harness />
      </ProjectProvider>,
    );

    await waitFor(() => expect(refreshed).toEqual([PROJECT_1]));
    // The list is re-read so every BrandLogo picks up the new URL together.
    await waitFor(() => expect(listCalls).toBeGreaterThan(1));
    // Idempotent: the now-hydrated project is not refreshed a second time.
    expect(refreshed).toEqual([PROJECT_1]);
  });

  it('does not retry a logo refresh that found no icon', async () => {
    const refreshed: string[] = [];
    mswServer.use(
      http.get('/api/v1/projects', () => HttpResponse.json([project(PROJECT_1, 'Acme')])),
      http.post('/api/v1/projects/:id/logos/refresh', ({ params }) => {
        refreshed.push(String(params.id));
        // No icon found — logo_url stays null.
        return HttpResponse.json(project(PROJECT_1, 'Acme'));
      }),
    );

    const { queryClient } = renderWithProviders(
      <ProjectProvider>
        <Harness />
      </ProjectProvider>,
    );

    await waitFor(() => expect(refreshed).toEqual([PROJECT_1]));
    // A refetch must not re-trigger the crawl: one attempt per project, period.
    await queryClient.invalidateQueries({ queryKey: ['projects', 'list'] });
    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('Acme'));
    expect(refreshed).toEqual([PROJECT_1]);
  });

  it('is empty (no active project) when the workspace has none', async () => {
    mswServer.use(http.get('/api/v1/projects', () => HttpResponse.json([])));

    renderWithProviders(
      <ProjectProvider>
        <Harness />
      </ProjectProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('0'));
    expect(screen.getByTestId('active')).toHaveTextContent('none');
    expect(getActiveWorkspaceId()).toBeNull();
  });
});
