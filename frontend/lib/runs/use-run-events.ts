'use client';

import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

import { API_BASE_URL, getActiveWorkspaceId } from '@/lib/api/client';
import { invalidationsFor, parseAuditEvent, parseFrame, splitFrames } from '@/lib/api/run-events';
import { queryKeys } from '@/lib/api/query-keys';
import {
  RUN_STREAM_INVALIDATE_DEBOUNCE_MS,
  RUN_STREAM_RECONNECT_BASE_MS,
  RUN_STREAM_RECONNECT_MAX_MS,
} from '@/lib/config/runs';

/**
 * Subscribe to a run's audit-event stream while `enabled`.
 *
 * SSE is ONLY an invalidation accelerator — the run page's polling stays the
 * baseline, so a dropped, blocked, or never-connecting stream never stops
 * progress and this hook never surfaces an error.
 *
 * Two properties keep the stream from becoming a load problem of its own:
 *
 *   - Invalidations are COALESCED. A 60-task run emits an event per task, and
 *     invalidating per event would fire dozens of overlapping refetches that
 *     resolve out of order — counts ticking backwards, rows appearing then
 *     vanishing. One trailing invalidation per burst gives the same freshness.
 *   - The stream RECONNECTS, resuming from the last event id, because the
 *     server closes it at its own duration cap. Without this a short run felt
 *     instant while a long one silently degraded to poll-only partway through.
 *
 * A credentialed `fetch` is used rather than `EventSource` because the backend
 * needs the `X-Workspace-Id` header to scope a non-default workspace's stream,
 * and `EventSource` can only issue a bare GET.
 */
export function useRunEvents(
  auditId: string | null | undefined,
  projectId: string | null | undefined,
  enabled: boolean,
): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled || !auditId) return;

    const controller = new AbortController();
    let cancelled = false;
    let invalidateTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let lastEventId: string | null = null;
    let pending = new Set<string>();

    const invalidateNow = () => {
      invalidateTimer = null;
      const families = pending;
      pending = new Set<string>();
      // Refetching through the normal endpoints keeps strict whole-response
      // validation on the only path that produces rows — an event payload is
      // never treated as a DTO, so replay and out-of-order delivery are safe.
      if (families.has('audit')) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.runs.detail(auditId) });
      }
      if (families.has('executions')) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.runs.executions(auditId) });
      }
      if (families.has('visibility') && projectId) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.visibility.all });
      }
    };

    const scheduleInvalidate = () => {
      if (invalidateTimer !== null) return;
      invalidateTimer = setTimeout(invalidateNow, RUN_STREAM_INVALIDATE_DEBOUNCE_MS);
    };

    const readFrame = (raw: string) => {
      const frame = parseFrame(raw);
      if (frame.id) lastEventId = frame.id;
      const event = parseAuditEvent(frame);
      if (event) {
        for (const family of invalidationsFor(event)) pending.add(family);
      } else if (frame.data) {
        // An unrecognised or drifted event still means SOMETHING changed. It
        // is not trusted as data, but refusing to refresh would be worse than
        // one extra refetch.
        pending.add('audit');
        pending.add('executions');
      }
      if (frame.data) scheduleInvalidate();
    };

    let framesThisConnection = 0;

    /** One connection. Resolves true when the server closed it cleanly. */
    const connect = async (): Promise<boolean> => {
      framesThisConnection = 0;
      const headers: Record<string, string> = { Accept: 'text/event-stream' };
      const workspaceId = getActiveWorkspaceId();
      if (workspaceId) headers['X-Workspace-Id'] = workspaceId;
      if (lastEventId) headers['Last-Event-ID'] = lastEventId;

      const response = await fetch(`${API_BASE_URL}/audits/${auditId}/events?stream=true`, {
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

      for (;;) {
        const { value, done } = await reader.read();
        if (done) return true;
        if (cancelled) return false;
        buffer += decoder.decode(value, { stream: true });
        const { frames, rest } = splitFrames(buffer);
        buffer = rest;
        for (const frame of frames) {
          readFrame(frame);
          framesThisConnection += 1;
        }
      }
    };

    const run = async (attempt = 0) => {
      let closedCleanly = false;
      try {
        closedCleanly = await connect();
      } catch (error) {
        if (cancelled || controller.signal.aborted) return;
        // Non-fatal by design: polling continues to advance the run. Logged at
        // error level so a stream failing every attempt is attributable rather
        // than silently invisible.
        console.error('[runs] audit event stream failed', { auditId, attempt, error });
      }
      if (cancelled || controller.signal.aborted) return; // Only a clean close that DELIVERED something is the server's duration
      // cap; a clean-but-empty close gets the same backoff as a failure, or an
      // instantly-closing stream becomes a permanent reconnect loop.
      const hitDurationCap = closedCleanly && framesThisConnection > 0;
      const delay = hitDurationCap
        ? RUN_STREAM_RECONNECT_BASE_MS
        : Math.min(RUN_STREAM_RECONNECT_BASE_MS * 2 ** attempt, RUN_STREAM_RECONNECT_MAX_MS);
      reconnectTimer = setTimeout(() => void run(hitDurationCap ? 0 : attempt + 1), delay);
    };

    void run();

    return () => {
      cancelled = true;
      if (invalidateTimer !== null) clearTimeout(invalidateTimer);
      if (reconnectTimer !== null) clearTimeout(reconnectTimer);
      controller.abort();
    };
  }, [auditId, projectId, enabled, queryClient]);
}
