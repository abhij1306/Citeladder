import Link from 'next/link';
import type { ReactNode } from 'react';

import { FlowShell } from '@/components/auth/flow-shell';

/**
 * Auth and onboarding share one focused light-ground flow shell.
 */
export default async function AuthLayout({ children }: Readonly<{ children: ReactNode }>) {
  'use cache';

  return (
    <FlowShell
      mainLabel="Account access"
      align="center"
      footer={
        <div className="website-label text-muted flex flex-wrap justify-center gap-x-1.5 text-center">
          <span>© {new Date().getFullYear()} CiteLadder</span>
          <span aria-hidden="true">·</span>
          <Link href="/privacy" className="hover:text-foreground transition-colors">
            Privacy
          </Link>
          <span aria-hidden="true">·</span>
          <Link href="/terms" className="hover:text-foreground transition-colors">
            Terms
          </Link>
        </div>
      }
    >
      <div className="flow-auth-content">{children}</div>
    </FlowShell>
  );
}
