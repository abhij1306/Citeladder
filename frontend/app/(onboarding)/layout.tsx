'use client';

import type { ReactNode } from 'react';

import { SessionGuard } from '@/lib/auth/session-guard';
import { ProjectProvider } from '@/lib/project/project-context';

/**
 * Onboarding is authenticated but deliberately has no application shell. It
 * still needs the same project context as the app because completion selects
 * the newly created project before navigating to the command center.
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
    <main
      id="main"
      className="bg-background grid min-h-dvh place-items-center p-[var(--page-section-gap)]"
    >
      <p className="text-muted text-sm">Loading your workspace…</p>
    </main>
  );
}
