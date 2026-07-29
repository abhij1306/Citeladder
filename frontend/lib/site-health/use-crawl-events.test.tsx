import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { setActiveWorkspaceId } from '@/lib/api/client';
import { queryKeys } from '@/lib/api/query-keys';
import { RECONNECT_BASE_MS, useCrawlEvents } from './use-crawl-events';

const CRAWL = '11111111-1111-4111-8111-111111111111';
const PROJECT = '22222222-2222-4222-8222-222222222222';

function makeStreamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return { ok: true, body } as unknown as Response;
}

function wrapper(client: QueryClient) {
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return Wrapper;
}

afterEach(() => {
  vi.restoreAllMocks();
  setActiveWorkspaceId(null);
});

describe('useCrawlEvents', () => {
  it('sends X-Workspace-Id and credentials, and invalidates on a data frame', async () => {
    setActiveWorkspaceId('99999999-9999-4999-8999-999999999999');
    const fetchMock = vi
      .fn()
      .mockResolvedValue(makeStreamResponse(['data: {"event_type":"page_updated"}\n\n']));
    vi.stubGlobal('fetch', fetchMock);

    const client = new QueryClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    renderHook(() => useCrawlEvents(CRAWL, PROJECT, true), { wrapper: wrapper(client) });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [, init] = fetchMock.mock.calls[0];
    expect(init.credentials).toBe('include');
    expect(init.headers['X-Workspace-Id']).toBe('99999999-9999-4999-8999-999999999999');

    // A data frame invalidates the crawl + pages queries (progress accelerator).
    // The list views carry a first-page predicate (`invalidateCrawlViews`), so
    // the assertion is on the key, not the whole filter object.
    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: queryKeys.siteHealth.pages(CRAWL) }),
      ),
    );
    vi.unstubAllGlobals();
  });

  it('does not open a stream when disabled', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const client = new QueryClient();
    renderHook(() => useCrawlEvents(CRAWL, PROJECT, false), { wrapper: wrapper(client) });
    expect(fetchMock).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it('coalesces a burst of events into ONE invalidation round', async () => {
    // The backend emits an `analysis.progress` event per analyzed URL, so a
    // large crawl would otherwise fire an invalidation round per URL, each
    // racing the screen's poll timers into out-of-order renders.
    const frames = Array.from(
      { length: 40 },
      (_, i) => `event: analysis.progress\nid: ${i}\ndata: {"analyzed":${i}}\n\n`,
    );
    const fetchMock = vi.fn().mockResolvedValue(makeStreamResponse(frames));
    vi.stubGlobal('fetch', fetchMock);

    const client = new QueryClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    renderHook(() => useCrawlEvents(CRAWL, PROJECT, true), { wrapper: wrapper(client) });

    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: queryKeys.siteHealth.pages(CRAWL) }),
      ),
    );
    // 40 events, 5 query keys: un-debounced that is 200 invalidate calls.
    const pagesCalls = invalidateSpy.mock.calls.filter(
      ([arg]) =>
        JSON.stringify((arg as { queryKey: unknown }).queryKey) ===
        JSON.stringify(queryKeys.siteHealth.pages(CRAWL)),
    );
    expect(pagesCalls.length).toBe(1);
    vi.unstubAllGlobals();
  });

  it('reconnects after a clean close, resuming from the last event id', async () => {
    // The server closes the stream at its max duration. Without a reconnect a
    // crawl longer than that silently degrades to poll-only partway through.
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(makeStreamResponse(['event: x\nid: evt-7\ndata: {"a":1}\n\n']))
      .mockResolvedValue(makeStreamResponse([]));
    vi.stubGlobal('fetch', fetchMock);

    const client = new QueryClient();
    renderHook(() => useCrawlEvents(CRAWL, PROJECT, true), { wrapper: wrapper(client) });

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(RECONNECT_BASE_MS + 50);
    await vi.waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(1));

    const [, retryInit] = fetchMock.mock.calls[1];
    expect(retryInit.headers['Last-Event-ID']).toBe('evt-7');

    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('stops reconnecting once the hook is torn down', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValue(makeStreamResponse([]));
    vi.stubGlobal('fetch', fetchMock);

    const client = new QueryClient();
    const { unmount } = renderHook(() => useCrawlEvents(CRAWL, PROJECT, true), {
      wrapper: wrapper(client),
    });

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    unmount();
    const afterUnmount = fetchMock.mock.calls.length;
    await vi.advanceTimersByTimeAsync(RECONNECT_BASE_MS * 5);
    expect(fetchMock.mock.calls.length).toBe(afterUnmount);

    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('swallows a failed stream so polling is never blocked', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('network'));
    vi.stubGlobal('fetch', fetchMock);
    const client = new QueryClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    renderHook(() => useCrawlEvents(CRAWL, PROJECT, true), { wrapper: wrapper(client) });

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    // No throw, no invalidation from a dead stream.
    expect(invalidateSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
