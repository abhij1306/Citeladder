'use client';

import type { ReactNode } from 'react';

import { Skeleton } from '@/components/ui/skeleton';
import { SessionGuard } from '@/lib/auth/session-guard';
import { ProjectProvider } from '@/lib/project/project-context';

/**
 * Onboarding route-group layout.
 *
 * SessionGuard + ProjectProvider, but deliberately **no AppShell**: onboarding
 * is a full-screen flow, and framing it in the sidebar chrome would imply the
 * workspace already exists.
 *
 * Unlike `(app)/layout.tsx` this does not redirect when projects exist — the
 * route is reachable on purpose for additional projects (`?new=1`), and a
 * blanket redirect here would break that. First-run routing is the gate's job
 * in `(app)`; this layout only supplies session and project context.
 */
export default function OnboardingLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <SessionGuard fallback={<OnboardingFallback />}>
      <ProjectProvider>{children}</ProjectProvider>
    </SessionGuard>
  );
}

function OnboardingFallback() {
  return (
    <div className="bg-background flex min-h-dvh items-center justify-center p-[var(--page-section-gap)]">
      <div className="grid w-full max-w-80 gap-3" aria-hidden>
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </div>
      <span className="sr-only">Loading…</span>
    </div>
  );
}
