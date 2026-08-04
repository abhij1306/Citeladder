import { QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

import { getActiveWorkspaceId, setActiveWorkspaceId } from '@/lib/api/client';
import { createAppQueryClient } from '@/lib/api/query-client';
import { queryKeys } from '@/lib/api/query-keys';
import { ACTIVE_PROJECT_STORAGE_KEY } from '@/lib/project/active-project-storage';
import { mswServer } from '@/test/msw-server';

import { useAuthMutation } from './use-auth-mutation';

// next/navigation is not available in jsdom — stub the router so we can assert
// on the post-success redirect (mirrors the auth page tests).
const replace = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn(), refresh: vi.fn() }),
}));

const sessionUser = {
  id: '11111111-1111-4111-8111-111111111111',
  email: 'user@example.com',
  role: 'owner',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const project = {
  id: '22222222-2222-4222-8222-222222222222',
  workspace_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  name: 'Acme',
  brand_name: 'Acme',
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

function setup(mutationFn: () => Promise<typeof sessionUser> = () => Promise.resolve(sessionUser)) {
  const queryClient = createAppQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  // The auth call itself is stubbed to resolve immediately — routing is driven
  // by the mocked `/projects` response.
  const hook = renderHook(() => useAuthMutation(mutationFn), { wrapper });
  return { queryClient, ...hook };
}

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  mswServer.resetHandlers();
  replace.mockReset();
  window.localStorage.clear();
  setActiveWorkspaceId(null);
});
afterAll(() => mswServer.close());

describe('useAuthMutation', () => {
  it('primes the me cache and routes to /onboarding when the workspace has no projects', async () => {
    mswServer.use(http.get('/api/v1/projects', () => HttpResponse.json([])));
    const { result, queryClient } = setup();

    act(() => {
      void result.current.submit({});
    });

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/onboarding'));
    expect(queryClient.getQueryData(queryKeys.auth.me())).toMatchObject({ id: sessionUser.id });
  });

  it('cancels old-account queries and clears only account-scoped state before seeding login', async () => {
    mswServer.use(http.get('/api/v1/projects', () => HttpResponse.json([])));
    const { result, queryClient } = setup();
    queryClient.setQueryData(['old-account', 'private'], { secret: 'stale' });
    window.localStorage.setItem(ACTIVE_PROJECT_STORAGE_KEY, project.id);
    window.localStorage.setItem('citeladder-theme', 'dark');
    setActiveWorkspaceId(project.workspace_id);

    let requestStarted: (() => void) | undefined;
    let wasAborted = false;
    const started = new Promise<void>((resolve) => {
      requestStarted = resolve;
    });
    const oldRequest = queryClient
      .fetchQuery({
        queryKey: ['old-account', 'in-flight'],
        queryFn: ({ signal }) =>
          new Promise<never>((_resolve, reject) => {
            requestStarted?.();
            signal.addEventListener(
              'abort',
              () => {
                wasAborted = true;
                reject(signal.reason);
              },
              { once: true },
            );
          }),
      })
      .catch(() => undefined);
    await started;

    act(() => {
      void result.current.submit({});
    });

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/onboarding'));
    await oldRequest;
    expect(wasAborted).toBe(true);
    expect(queryClient.getQueryData(['old-account', 'private'])).toBeUndefined();
    expect(queryClient.getQueryData(queryKeys.auth.me())).toMatchObject({ id: sessionUser.id });
    expect(window.localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY)).toBeNull();
    expect(window.localStorage.getItem('citeladder-theme')).toBe('dark');
    expect(getActiveWorkspaceId()).toBeNull();
  });

  it('does not clear the existing account state when authentication fails', async () => {
    const { result, queryClient } = setup(() => Promise.reject(new Error('invalid credentials')));
    queryClient.setQueryData(['old-account', 'private'], { stays: true });
    window.localStorage.setItem(ACTIVE_PROJECT_STORAGE_KEY, project.id);
    setActiveWorkspaceId(project.workspace_id);

    await act(async () => {
      await result.current.submit({});
    });

    await waitFor(() => expect(result.current.mutation.isError).toBe(true));
    expect(queryClient.getQueryData(['old-account', 'private'])).toEqual({ stays: true });
    expect(window.localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY)).toBe(project.id);
    expect(getActiveWorkspaceId()).toBe(project.workspace_id);
    expect(replace).not.toHaveBeenCalled();
  });

  it('routes to /projects when the workspace already has a project', async () => {
    mswServer.use(http.get('/api/v1/projects', () => HttpResponse.json([project])));
    const { result } = setup();

    act(() => {
      void result.current.submit({});
    });

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/projects'));
  });

  // A pricing selection captured before signing in was the visitor's last
  // deliberate action; landing them on /projects would silently discard it.
  it('resumes a captured pricing intent instead of the normal destination', async () => {
    mswServer.use(http.get('/api/v1/projects', () => HttpResponse.json([project])));
    globalThis.sessionStorage.setItem(
      'citeladder.pendingPricingIntent.v1',
      JSON.stringify({
        version: 1,
        kind: 'checkout',
        catalog_key: 'tier_2',
        quantity: 1,
        byok: true,
        country_code: null,
        idempotency_key: 'idem-1',
        return_path: '/pricing',
        created_at_ms: Date.now(),
      }),
    );
    const { result } = setup();

    act(() => {
      void result.current.submit({});
    });

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/pricing?resumeActivation=1'));
    // No intent field may leak into the auth URL — the record stays in
    // storage and is revalidated against the live catalog before any purchase.
    expect(replace).not.toHaveBeenCalledWith(expect.stringContaining('tier_2'));
    globalThis.sessionStorage.clear();
  });

  it('ignores a malformed stored intent and uses the normal destination', async () => {
    mswServer.use(http.get('/api/v1/projects', () => HttpResponse.json([project])));
    globalThis.sessionStorage.setItem('citeladder.pendingPricingIntent.v1', '{"version":99}');
    const { result } = setup();

    act(() => {
      void result.current.submit({});
    });

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/projects'));
    globalThis.sessionStorage.clear();
  });

  it('falls back to /onboarding when the projects lookup fails', async () => {
    // 4xx: the shared retry policy never retries it, so the fallback is
    // immediate.
    mswServer.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ detail: 'forbidden' }, { status: 403 }),
      ),
    );
    const { result } = setup();

    act(() => {
      void result.current.submit({});
    });

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/onboarding'));
    expect(result.current.mutation.isError).toBe(false);
  });

  it('stays pending until the projects lookup settles and the redirect fires', async () => {
    let respond: ((response: Response) => void) | undefined;
    mswServer.use(
      http.get(
        '/api/v1/projects',
        () =>
          new Promise<Response>((resolve) => {
            respond = resolve;
          }),
      ),
    );
    const { result } = setup();

    act(() => {
      void result.current.submit({});
    });

    await waitFor(() => expect(result.current.mutation.isPending).toBe(true));
    expect(replace).not.toHaveBeenCalled();

    // isPending flips before the MSW handler has necessarily assigned
    // `respond` — wait for the request to actually arrive before resolving.
    await waitFor(() => expect(respond).toBeTypeOf('function'));
    if (!respond) throw new Error('Projects request did not start');
    respond(HttpResponse.json([]));
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/onboarding'));
    await waitFor(() => expect(result.current.mutation.isPending).toBe(false));
  });
});
