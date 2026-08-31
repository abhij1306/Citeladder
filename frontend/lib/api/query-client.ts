/**
 * TanStack Query client factory + retry policy (F2).
 *
 * `shouldRetryQuery`: retry transient failures only — network errors and
 * 408/429/5xx — capped at 2 attempts. 4xx (except 408/429) and aborts never
 * retry. When the backend (or the A3 timeout surface) classifies the failure
 * with an explicit `retryable` flag, that classification wins — an A3
 * `request_timeout` ApiError carries `retryable: true` and slots in here.
 * `staleTime` 15s and `refetchOnWindowFocus:false` match the reference
 * frontend. Mutations never auto-retry.
 */
import { QueryClient } from '@tanstack/react-query';

import { ApiError, httpErrorStatus, isAbortError } from './errors';

export function shouldRetryQuery(failureCount: number, error: unknown) {
  if (failureCount >= 2 || isAbortError(error)) return false;
  if (error instanceof ApiError && typeof error.retryable === 'boolean') {
    return error.retryable;
  }
  const status = httpErrorStatus(error);
  if (status === undefined) return true; // network / unknown → retry
  return status === 408 || status === 429 || status >= 500;
}

/**
 * Retain the prior result only while the query stays inside the same
 * project/crawl scope. Filter and cursor changes keep their mounted content,
 * while changing the active project cannot temporarily relabel another
 * project's persisted evidence as the newly selected project.
 *
 * Domain query keys place their owning project or crawl id at index 2.
 */
export function retainPreviousDataForScope<TData>(
  scopeId: string,
  previousData: TData | undefined,
  previousQuery: { queryKey: readonly unknown[] } | undefined,
): TData | undefined {
  return previousQuery?.queryKey[2] === scopeId ? previousData : undefined;
}

export function createAppQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetryQuery,
        staleTime: 15_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}
