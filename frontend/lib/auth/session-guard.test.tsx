import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';

import { useQuery, type QueryClient } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/errors';
import { runsApi } from '@/lib/api/runs';
import { getActiveWorkspaceId, setActiveWorkspaceId } from '@/lib/api/client';
import { queryKeys } from '@/lib/api/query-keys';
import { ACTIVE_PROJECT_STORAGE_KEY } from '@/lib/project/active-project-storage';
import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';

const replace = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn(), refresh: vi.fn() }),
}));

import { SessionGuard, useSessionUser } from './session-guard';

const sessionUser = {
  id: '22222222-2222-4222-8222-222222222222',
  email: 'guarded@example.com',
  role: 'owner',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function Protected() {
  const user = useSessionUser();
  return <div>signed in as {user.email}</div>;
}

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  mswServer.resetHandlers();
  replace.mockReset();
  window.localStorage.clear();
  setActiveWorkspaceId(null);
});
afterAll(() => mswServer.close());

describe('SessionGuard', () => {
  it('renders protected content for an authenticated user', async () => {
    mswServer.use(http.get('/api/v1/auth/me', () => HttpResponse.json({ user: sessionUser })));

    renderWithProviders(
      <SessionGuard fallback={<div>loading</div>}>
        <Protected />
      </SessionGuard>,
    );

    expect(await screen.findByText(/signed in as guarded@example.com/i)).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it('redirects unauthenticated visitors to /login', async () => {
    let requestCount = 0;
    mswServer.use(
      http.get('/api/v1/auth/me', () => {
        requestCount += 1;
        return HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 });
      }),
    );

    renderWithProviders(
      <SessionGuard fallback={<div>loading</div>}>
        <Protected />
      </SessionGuard>,
    );

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/login'));
    await new Promise((resolve) => {
      setTimeout(resolve, 50);
    });
    expect(requestCount).toBe(1);
    expect(screen.queryByText(/signed in as/i)).not.toBeInTheDocument();
  });

  it('does not log the user out when /auth/me fails with a non-401 error', async () => {
    // A non-401 error (here a 403; also a network blip / 5xx) is not a session
    // expiry — the guard must NOT clear the session or redirect to /login.
    mswServer.use(
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({ detail: 'Forbidden' }, { status: 403 }),
      ),
    );

    renderWithProviders(
      <SessionGuard fallback={<div>loading</div>}>
        <Protected />
      </SessionGuard>,
    );

    // The guard stays on the fallback (no user) but never bounces to /login.
    await screen.findByText('loading');
    await new Promise((resolve) => {
      setTimeout(resolve, 50);
    });
    expect(replace).not.toHaveBeenCalled();
  });

  it('clears the session and redirects when any query returns 401', async () => {
    // `me` succeeds so protected content mounts, then a downstream query 401s
    // (an expired cookie mid-session) — the guard's watchdog must clear + bounce.
    mswServer.use(
      http.get('/api/v1/auth/me', () => HttpResponse.json({ user: sessionUser })),
      http.get('/api/v1/audits', () =>
        HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 }),
      ),
    );

    function ChildQuery() {
      useQuery({
        queryKey: queryKeys.runs.list(),
        queryFn: ({ signal }) => runsApi.listAudits(undefined, { signal }),
      });
      return <Protected />;
    }

    window.localStorage.setItem(ACTIVE_PROJECT_STORAGE_KEY, 'old-project');
    window.localStorage.setItem('searchify-theme', 'dark');
    setActiveWorkspaceId('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa');

    const { queryClient } = renderWithProviders(
      <SessionGuard fallback={<div>loading</div>}>
        <ChildQuery />
      </SessionGuard>,
    );

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/login'));
    // Session cache was cleared.
    expect(queryClient.getQueryData(queryKeys.auth.me())).toBeUndefined();
    expect(window.localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY)).toBeNull();
    expect(window.localStorage.getItem('searchify-theme')).toBe('dark');
    expect(getActiveWorkspaceId()).toBeNull();
  });

  it('acts on a 401 reaching the cache directly, after the deferring microtask', async () => {
    // The watchdog defers to a microtask because Effect Events may not be
    // called during render, and React Query notifies subscribers synchronously
    // — sometimes mid-render. This drives the cache itself rather than an HTTP
    // query, so the subscription + deferral are exercised on their own.
    mswServer.use(http.get('/api/v1/auth/me', () => HttpResponse.json({ user: sessionUser })));

    const { queryClient } = renderWithProviders(
      <SessionGuard fallback={<div>loading</div>}>
        <Protected />
      </SessionGuard>,
    );
    await screen.findByText(/signed in as guarded@example.com/i);

    await expect(reject401(queryClient, 'while-mounted')).rejects.toThrow();
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/login'));
  });

  it('stops acting on cache 401s once unmounted', async () => {
    // Teardown: `unsubscribe()` plus the `disposed` latch covering callbacks
    // already queued on the microtask when the guard went away. Nothing is
    // triggered before unmounting on purpose — `clearSession`'s own
    // `redirectingRef` latch would otherwise swallow the second redirect and
    // the test would pass with the teardown deleted.
    mswServer.use(http.get('/api/v1/auth/me', () => HttpResponse.json({ user: sessionUser })));

    const { queryClient, unmount } = renderWithProviders(
      <SessionGuard fallback={<div>loading</div>}>
        <Protected />
      </SessionGuard>,
    );
    await screen.findByText(/signed in as guarded@example.com/i);

    unmount();

    await expect(reject401(queryClient, 'after-unmount')).rejects.toThrow();
    await new Promise((resolve) => {
      setTimeout(resolve, 50);
    });
    expect(replace).not.toHaveBeenCalled();
  });
});

/** Drive a real errored `'updated'` cache event carrying a 401. */
function reject401(queryClient: QueryClient, key: string) {
  return queryClient.fetchQuery({
    queryKey: [key],
    queryFn: () => Promise.reject(new ApiError('Unauthorized', 401, '')),
    retry: false,
  });
}
