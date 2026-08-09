import Link from 'next/link';
import type { ReactNode } from 'react';

import { AuthBrandPanel, AuthWordmark } from '@/components/auth/brand-panel';

/**
 * Auth route-group layout matching reference split-screen design.
 *
 * 50/50 split at ≥900px: left dark panel with centered brand mark,
 * right clean white canvas containing the auth form and footer.
 */
export default function AuthLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <div className="website-type bg-panel text-foreground relative min-h-dvh w-full overflow-hidden antialiased min-[900px]:grid min-[900px]:grid-cols-2">
      <AuthBrandPanel />

      <main
        id="main"
        className="bg-panel relative flex min-h-dvh flex-col justify-between px-6 py-8 sm:px-12 lg:px-16"
      >
        {/* Mobile wordmark header */}
        <header className="flex items-center justify-between gap-3 min-[900px]:hidden">
          <AuthWordmark compact />
        </header>

        <div className="flex flex-1 items-center justify-center py-6">
          <div className="w-full max-w-sm sm:max-w-md">{children}</div>
        </div>

        {/* Footer band. Privacy and Terms are LINKS: rendering the words of a
            legal notice as inert text on the screen where an account is
            created offers a policy the reader cannot go and read. */}
        <footer className="website-label text-muted flex flex-wrap justify-center gap-x-1.5 pb-2 text-center">
          <span>© {new Date().getFullYear()} CiteLadder</span>
          <span aria-hidden="true">·</span>
          <Link href="/privacy" className="hover:text-foreground transition-colors">
            Privacy
          </Link>
          <span aria-hidden="true">·</span>
          <Link href="/terms" className="hover:text-foreground transition-colors">
            Terms
          </Link>
        </footer>
      </main>
    </div>
  );
}
