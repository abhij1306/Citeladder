import { ACTIVE_RUN_POLL_MS } from '@/lib/config/operational';

/**
 * Task statuses that mean work is still coming. Anything else is finished, so
 * the projection counts cannot change again on their own.
 */
const IN_FLIGHT_STATUSES = ['queued', 'leased', 'running', 'retry_wait'] as const;

/**
 * How often to re-read the catalog, or `false` to stop.
 *
 * The Catalog tab polled every three seconds for as long as it was open, even
 * with nothing projecting — a request every three seconds, forever, to learn
 * that a finished crawl was still finished. Poll while projection tasks are
 * actually in flight, then stop.
 *
 * Pure and exported so the rule is testable without mounting the screen.
 */
export function catalogPollingInterval(
  projectionTasks: Record<string, number> | undefined,
): number | false {
  if (!projectionTasks) return false;
  const inFlight = IN_FLIGHT_STATUSES.some((status) => (projectionTasks[status] ?? 0) > 0);
  return inFlight ? ACTIVE_RUN_POLL_MS : false;
}
