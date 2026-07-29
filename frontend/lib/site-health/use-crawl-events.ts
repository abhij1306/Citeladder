'use client';

/**
 * Credentialed Site Health crawl-event stream (Slice 7).
 *
 * SSE is ONLY an invalidation accelerator — polling (in the screen) is the
 * reliable baseline. When a `crawl_updated` / page / event arrives on the
 * stream we invalidate the relevant Site Health queries so rows move
 * queued → running → completed/error/blocked without waiting for the next poll
 * tick. A dropped, timed-out, or disconnected stream MUST NOT stop progress:
 * this hook never surfaces a fatal error and the screen keeps polling.
 *
 * We use an abortable credentialed `fetch` + `ReadableStream` reader rather than
 * the native `EventSource`, because `EventSource` cannot send the
 * `X-Workspace-Id` header the backend needs to scope a non-default workspace's
 * stream (it only issues a bare same-origin GET). `apiClient` is JSON-only, so
 * this is the one place we call `fetch` directly — with the same credentials +
 * workspace header contract.
 *
 * Two properties keep the stream from becoming a load problem of its own:
 *
 *   - Invalidations are COALESCED. The backend emits an `analysis.progress`
 *     event per analyzed URL, so a 500-URL crawl would otherwise fire ~2,500
 *     invalidation rounds over 5 query keys, each racing the screen's poll
 *     timers. Overlapping refetches then resolve out of order and panels render
 *     state from different moments (counts ticking backwards, a score appearing
 *     then vanishing). One trailing invalidation per burst gives the same
 *     freshness for a fraction of the requests.
 *   - The stream RECONNECTS. The server closes it at `sse_max_duration_seconds`
 *     (300s), so without this a crawl under 5 minutes felt instant while a
 *     longer one silently degraded to poll-only partway through — identical
 *     code, two different behaviours. Each attempt resumes from the last seen
 *     event id (`Last-Event-ID`), so nothing is replayed.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

import { API_BASE_URL, getActiveWorkspaceId } from '@/lib/api/client';
import { queryKeys } from '@/lib/api/query-keys';

/** Trailing-edge window for coalescing a burst of stream events. */
export const INVALIDATE_DEBOUNCE_MS = 500;

/** Reconnect backoff bounds after a stream closes. */
export const RECONNECT_BASE_MS = 1_000;
export const RECONNECT_MAX_MS = 15_000;

/**
 * Subscribe to a crawl's SSE event stream while `enabled`. Bursts of events are
 * coalesced into one invalidation of the crawl + pages + inventory + issues +
 * dashboard queries, and the stream reconnects (resuming from the last event
 * id) until the effect is torn down. All failures are swallowed — polling
 * remains the source of progress.
 */
export function useCrawlEvents(
  crawlId: string | null | undefined,
  projectId: string | null | undefined,
  enabled: boolean,
): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled || !crawlId) return;

    const controller = new AbortController();
    let cancelled = false;
    let invalidateTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let lastEventId: string | null = null;

    const invalidateNow = () => {
      invalidateTimer = null;
      // Move page rows through their lifecycle and refresh the crawl summary +
      // dashboard scores. Invalidate ALL page/inventory/issue queries for this
      // crawl (every filter/cursor combination), never just one client page.
      queryClient.invalidateQueries({ queryKey: queryKeys.siteHealth.crawl(crawlId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.siteHealth.pages(crawlId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.siteHealth.inventory(crawlId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.siteHealth.issues(crawlId) });
      if (projectId) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.siteHealth.dashboard(projectId),
        });
      }
    };

    /** Coalesce a burst of events into ONE trailing invalidation. */
    const scheduleInvalidate = () => {
      if (invalidateTimer !== null) return;
      invalidateTimer = setTimeout(invalidateNow, INVALIDATE_DEBOUNCE_MS);
    };

    /** Track `id:` lines so a reconnect resumes instead of replaying. */
    const readFrame = (frame: string) => {
      let sawData = false;
      for (const line of frame.split('\n')) {
        // Ignore keep-alive comments (":" prefix); invalidate on any data.
        if (line.startsWith('data:')) sawData = true;
        else if (line.startsWith('id:')) lastEventId = line.slice(3).trim();
      }
      if (sawData) scheduleInvalidate();
    };

    /** One connection. Resolves true when the server closed it cleanly. */
    const connect = async (): Promise<boolean> => {
      const headers: Record<string, string> = { Accept: 'text/event-stream' };
      const workspaceId = getActiveWorkspaceId();
      if (workspaceId) headers['X-Workspace-Id'] = workspaceId;
      if (lastEventId) headers['Last-Event-ID'] = lastEventId;

      const response = await fetch(`${API_BASE_URL}/site-crawls/${crawlId}/events?stream=true`, {
        method: 'GET',
        headers,
        credentials: 'include',
        cache: 'no-store',
        signal: controller.signal,
      });
      if (!response.ok || !response.body) return false;

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      // Read frames until the stream ends (terminal grace / max duration) or
      // the effect is torn down.
      for (;;) {
        const { value, done } = await reader.read();
        if (done) return true;
        if (cancelled) return false;
        buffer += decoder.decode(value, { stream: true });
        // SSE frames are separated by a blank line.
        let sep = buffer.indexOf('\n\n');
        while (sep !== -1) {
          readFrame(buffer.slice(0, sep));
          buffer = buffer.slice(sep + 2);
          sep = buffer.indexOf('\n\n');
        }
      }
    };

    // Reconnect while the crawl is still active (`enabled` drops on terminal,
    // tearing the effect down). A clean close is the server's normal duration
    // cap, so it reconnects promptly and resets the backoff; only genuine
    // failures (server down, auth lost) back off toward the cap.
    const run = async (attempt = 0) => {
      let closedCleanly = false;
      try {
        closedCleanly = await connect();
      } catch {
        // Dropped / aborted / timed-out streams are non-fatal: polling in the
        // screen continues to advance progress. Swallow silently.
      }
      if (cancelled || controller.signal.aborted) return;
      const delay = closedCleanly
        ? RECONNECT_BASE_MS
        : Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS);
      reconnectTimer = setTimeout(() => void run(closedCleanly ? 0 : attempt + 1), delay);
    };

    void run();

    return () => {
      cancelled = true;
      if (invalidateTimer !== null) clearTimeout(invalidateTimer);
      if (reconnectTimer !== null) clearTimeout(reconnectTimer);
      controller.abort();
    };
  }, [crawlId, projectId, enabled, queryClient]);
}
