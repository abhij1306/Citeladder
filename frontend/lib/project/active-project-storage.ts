import { setActiveWorkspaceId } from '@/lib/api/client';

export const ACTIVE_PROJECT_STORAGE_KEY = 'citeladder.active-project-id';

/** Read the persisted active-project id (SSR-safe: null on the server). */
export function readStoredActiveProjectId(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function writeStoredActiveProjectId(projectId: string | null) {
  if (typeof window === 'undefined') return;
  try {
    if (projectId) window.localStorage.setItem(ACTIVE_PROJECT_STORAGE_KEY, projectId);
    else window.localStorage.removeItem(ACTIVE_PROJECT_STORAGE_KEY);
  } catch {
    // Ignore storage failures (private mode / quota) — selection stays in memory.
  }
}

/** Remove only account-scoped project state; preferences such as theme remain. */
export function clearActiveProjectSelection() {
  writeStoredActiveProjectId(null);
  setActiveWorkspaceId(null);
}
