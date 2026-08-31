'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { projectsApi } from '@/lib/api/projects';
import { queryKeys } from '@/lib/api/query-keys';
import type { SessionUser } from '@/lib/api/types';
import { clearAccountScopedClientState } from '@/lib/auth/account-transition';
import { hasPendingIntent } from '@/lib/billing/pending-pricing-intent';
import { PRICING_RESUME_QUERY_PARAM, PRICING_RETURN_PATH } from '@/lib/config/billing';
import { hardNavigate } from '@/lib/navigation/hard-navigate';

/**
 * Login mutation wiring (F4): on success, prime the `me` cache
 * with the returned user and route directly to the right authed screen — no
 * marketing-landing bounce. The project list is fetched through the query
 * client and awaited, which keeps the mutation pending until the destination is
 * known: no projects yet → `/onboarding`, otherwise `/projects`. The confirmed
 * identity boundary uses a full-page navigation so the protected layout reads
 * the new cookie and session state from a clean document instead of reusing a
 * prefetched anonymous shell. A failed lookup falls back to `/onboarding`.
 */
export function useAuthMutation<TValues>(mutationFn: (values: TValues) => Promise<SessionUser>) {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn,
    onSuccess: async (user: SessionUser) => {
      // Login is an identity boundary. Remove the previous account's
      // requests, cache, active workspace header, and project selection before
      // the newly-confirmed identity is seeded.
      await clearAccountScopedClientState(queryClient);
      queryClient.setQueryData(queryKeys.auth.me(), user);

      // A pricing selection captured before signing in wins over onboarding:
      // the visitor's last deliberate action was choosing a plan, and dropping
      // them on /projects would silently discard it. The flag is all that
      // travels — the intent itself stays in storage and is revalidated
      // against the live catalog before anything is purchased.
      if (hasPendingIntent()) {
        hardNavigate(`${PRICING_RETURN_PATH}?${PRICING_RESUME_QUERY_PARAM}=1`);
        return;
      }

      let destination = '/onboarding';
      try {
        const projects = await queryClient.fetchQuery({
          queryKey: queryKeys.projects.list(),
          queryFn: ({ signal }) => projectsApi.listProjects({ signal }),
        });
        if (projects.length > 0) destination = '/projects';
      } catch {
        // Projects lookup failed — `/onboarding` is the safe default.
      }
      hardNavigate(destination);
    },
  });

  const submit = (values: TValues) => mutation.mutateAsync(values).catch(() => undefined);

  return { mutation, submit };
}
