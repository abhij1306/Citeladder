'use client';

/**
 * Credentialed Site Health crawl-event stream (Slice 7).
 *
 * SSE is ONLY an invalidation accelerator — polling (in the screen) is the
 * reliable baseline. Lifecycle and terminal events refresh the dashboard
 * immediately; high-frequency per-page progress stays on the bounded poll.
 * A dropped, timed-out, or disconnected stream MUST NOT stop progress: this
 * hook never surfaces a fatal error and the screen keeps polling.
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
 *   - Per-page progress events do not invalidate queries. The dashboard's
 *     bounded poll already observes them; lifecycle events are coalesced and
 *     refresh only that single subscription, which fans out once on change.
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
import {
  SITE_HEALTH_STREAM_INVALIDATE_DEBOUNCE_MS,
  SITE_HEALTH_STREAM_RECONNECT_BASE_MS,
  SITE_HEALTH_STREAM_RECONNECT_MAX_MS,
} from '@/lib/config/site-health';
import { invalidateCrawlViews } from '@/lib/site-health/invalidate';

/**
 * Subscribe to a crawl's SSE event stream while `enabled`. Lifecycle bursts
 * coalesce into one dashboard invalidation, and the stream reconnects (resuming
 * from the last event id) until the effect is torn down. All failures are
 * swallowed — polling remains the source of progress.
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
      // The dashboard projection is the single subscription. Once it lands,
      // useSiteHealthScreen compares its progress fingerprint and refreshes
      // the derived first-page views exactly once. Invalidating every list here
      // as well doubled the request fan-out for each stream event.
      if (projectId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.siteHealth.dashboard(projectId) });
      } else {
        invalidateCrawlViews(queryClient, crawlId);
      }
    };

    /** Coalesce a burst of events into ONE trailing invalidation. */
    const scheduleInvalidate = () => {
      if (invalidateTimer !== null) return;
      invalidateTimer = setTimeout(invalidateNow, SITE_HEALTH_STREAM_INVALIDATE_DEBOUNCE_MS);
    };

    /** Track `id:` lines so a reconnect resumes instead of replaying. */
    const readFrame = (frame: string) => {
      let sawData = false;
      let eventType: string | null = null;
      for (const line of frame.split('\n')) {
        // Ignore keep-alive comments (":" prefix); invalidate on any data.
        if (line.startsWith('data:')) {
          sawData = true;
          try {
            const payload = JSON.parse(line.slice(5).trim()) as { event_type?: unknown };
            if (typeof payload.event_type === 'string') eventType = payload.event_type;
          } catch {
            // Unknown frames still trigger a conservative lifecycle refresh.
          }
        } else if (line.startsWith('id:')) lastEventId = line.slice(3).trim();
      }
      // Per-page progress is already covered by the dashboard's bounded poll.
      // Refetch immediately only for lifecycle/terminal events, where waiting
      // for the next poll would leave stale controls or completion state.
      if (sawData && !eventType?.endsWith('.progress')) scheduleInvalidate();
    };

    // Frames delivered by the connection currently being read. A clean close is
    // only treated as "the server's duration cap" — the case that deserves a
    // prompt reconnect with the backoff reset — when the connection actually
    // did something. Otherwise an immediately-closing stream (terminal crawl
    // already flushed, a proxy that will not hold streams open, an empty body)
    // is indistinguishable from the 300s cap and reconnects forever at
    // the base reconnect interval with no backoff.
    let framesThisConnection = 0;

    /** One connection. Resolves true when the server closed it cleanly. */
    const connect = async (): Promise<boolean> => {
      framesThisConnection = 0;
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
          framesThisConnection += 1;
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
      } catch (error) {
        if (cancelled || controller.signal.aborted) return;
        // Dropped / aborted / timed-out streams are non-fatal: polling in the
        // screen continues to advance progress, so the failure is swallowed
        // and a reconnect is still scheduled below. It is logged at error
        // level (never surfaced) so a stream that is failing every attempt is
        // attributable in the console instead of silently invisible.
        console.error('[site-health] crawl event stream failed', {
          crawlId,
          attempt,
          error,
        });
      }
      if (cancelled || controller.signal.aborted) return; // Only a clean close that DELIVERED something is the server's duration
      // cap; a clean-but-empty close gets the same backoff as a failure, or an
      // instantly-closing stream becomes a permanent 1 req/s loop.
      const hitDurationCap = closedCleanly && framesThisConnection > 0;
      const delay = hitDurationCap
        ? SITE_HEALTH_STREAM_RECONNECT_BASE_MS
        : Math.min(
            SITE_HEALTH_STREAM_RECONNECT_BASE_MS * 2 ** attempt,
            SITE_HEALTH_STREAM_RECONNECT_MAX_MS,
          );
      reconnectTimer = setTimeout(() => void run(hitDurationCap ? 0 : attempt + 1), delay);
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
