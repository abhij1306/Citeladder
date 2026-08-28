'use client';

import { useRouter } from 'next/navigation';
import { useEffect, type ReactNode } from 'react';

import { Skeleton } from '@/components/ui/skeleton';
import { useProjectContext } from '@/lib/project/project-context';

/**
 * First-run gate — sends users with zero projects to `/onboarding`.
 *
 * Sits between ProjectProvider and AppShell so every `(app)` route is covered
 * by one redirect instead of each screen inventing its own empty state.
 *
 * Two race conditions, both explicit requirements (plan.md Task 11):
 *
 * (a) **No flash for users who have projects.** `projects` is `[]` while the
 *     query is still in flight, which is indistinguishable from "no projects"
 *     if you only look at length. Waiting for `isLoading` to settle is what
 *     stops an existing user being bounced to onboarding for a frame.
 *
 * (b) **No bounce-back after confirm.** Onboarding awaits the projects refetch
 *     before navigating here, so by the time this mounts the list is warm. The
 *     skeleton below covers the gap either way rather than rendering the app
 *     against an empty context.
 */
export function OnboardingGate({ children }: Readonly<{ children: ReactNode }>) {
  const router = useRouter();
  const { projects, isLoading } = useProjectContext();
  const needsOnboarding = !isLoading && projects.length === 0;

  useEffect(() => {
    if (needsOnboarding) {
      // Project availability is client-fetched; the skeleton prevents a page flash.
      router.replace('/onboarding');
    }
  }, [needsOnboarding, router]);

  if (isLoading || needsOnboarding) {
    return (
      <div className="bg-background flex min-h-dvh items-center justify-center p-[var(--card-padding)]">
        <div className="grid w-full max-w-70 gap-3" aria-hidden>
          <Skeleton className="h-6 w-32" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
        <span className="sr-only">Loading your workspace…</span>
      </div>
    );
  }

  return <>{children}</>;
}
