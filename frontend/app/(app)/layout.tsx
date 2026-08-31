import { Suspense, type ReactNode } from 'react';

import { AppShell } from '@/components/layout/app-shell';
import { OnboardingGate } from '@/components/layout/onboarding-gate';
import { Skeleton } from '@/components/ui/skeleton';
import { SessionGuard } from '@/lib/auth/session-guard';
import { EntitlementProvider } from '@/lib/billing/entitlement-context';
import { ProjectProvider } from '@/lib/project/project-context';
import { ProductTourProvider } from '@/components/tour/product-tour-provider';
import { ProductMotionProvider } from '@/components/providers/product-motion-provider';
import { ToastProvider } from '@/components/ui/toast';

/** Validate that the authenticated shell can render immediately on navigation. */
export const instant = true;

/**
 * Authed-area layout (F5).
 *
 * Wraps every `(app)` route in F4's `<SessionGuard>` (bounces unauthenticated
 * visitors to `/login` and installs the 401 watchdog), then the F5
 * `<ProjectProvider>` (active-project context + `X-Workspace-Id` header wiring),
 * then `<OnboardingGate>` (first-run users have no project yet, so they go to
 * `/onboarding` rather than into an empty workspace), then the `<AppShell>`
 * chrome (sidebar + top bar). `/` is now the public marketing page (see
 * `app/(marketing)/`); its LandingSessionRedirect island forwards signed-in
 * visitors here (`/projects`, or `/onboarding` pre-project).
 */
export default function AppLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <SessionGuard fallback={<ShellFallback />}>
      <ProjectProvider>
        <Suspense fallback={<ShellFallback />}>
          <ProductTourProvider>
            <EntitlementProvider>
              <ProductMotionProvider>
                <ToastProvider>
                  <OnboardingGate>
                    <AppShell>{children}</AppShell>
                  </OnboardingGate>
                </ToastProvider>
              </ProductMotionProvider>
            </EntitlementProvider>
          </ProductTourProvider>
        </Suspense>
      </ProjectProvider>
    </SessionGuard>
  );
}

function ShellFallback() {
  return (
    <div className="bg-background flex min-h-dvh items-center justify-center p-[var(--card-padding)]">
      <div className="grid w-full max-w-72 gap-4" aria-hidden>
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </div>
      <span className="sr-only">Loading your workspace…</span>
    </div>
  );
}
