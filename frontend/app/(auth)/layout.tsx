import type { ReactNode } from 'react';

import { AuthBrandPanel, AuthWordmark } from '@/components/auth/brand-panel';

/**
 * Auth route-group layout, on the Proof surface.
 *
 * Split screen at ≥900px, **asymmetric on purpose**: the brand panel takes
 * 5/12 and the form 7/12. A 50/50 split gives equal weight to marketing copy
 * and the thing the user came to do, which is what makes the screen read as
 * flat — a sign-in page should lean toward the form.
 *
 * Both columns share one three-band rhythm — header / centred body / footer —
 * so the wordmark, the form and the fine print line up across the divide
 * instead of each column floating its own way. Below 900px the brand panel
 * drops and the form keeps the same bands.
 *
 * `.mkt-root` scopes the Proof system (light-only canvas, focus ring). There
 * is no ThemeToggle here: Proof is a light-only identity, and a toggle that
 * changed nothing would be a broken control.
 *
 * The single-h1 rule: the pages own the only h1 — the wordmarks are spans,
 * and the brand headline is a `<p>`.
 */
export default function AuthLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <div className="mkt-root bg-mkt-paper-raised text-mkt-ink selection:bg-mkt-proof relative min-h-dvh w-full overflow-hidden antialiased selection:text-white min-[900px]:grid min-[900px]:grid-cols-12">
      {/* Subtle light ambient background lighting */}
      <div className="pointer-events-none absolute inset-0 -z-10">
        <div className="bg-mkt-proof-soft/50 absolute -top-40 -left-40 size-[500px] rounded-full blur-[120px]" />
        <div className="bg-mkt-sky/50 absolute -right-40 -bottom-40 size-[500px] rounded-full blur-[120px]" />
        <div className="bg-mkt-proof-soft/30 absolute top-1/2 left-1/2 size-[600px] -translate-x-1/2 -translate-y-1/2 rounded-full blur-[100px]" />
      </div>

      <AuthBrandPanel />

      <main className="relative flex min-h-dvh flex-col justify-between px-6 py-8 min-[900px]:col-span-7 sm:px-10 lg:px-16">
        {/* Header band — mobile wordmark */}
        <header className="flex items-center justify-between gap-3">
          <div className="min-[900px]:invisible">
            <AuthWordmark compact />
          </div>
        </header>

        <div className="flex flex-1 items-center justify-center py-8">
          <div className="w-full max-w-md">
            {children}

            {/* Mobile reassurance pills - No separating border lines */}
            <ul className="text-mkt-ink-soft mt-8 flex flex-wrap items-center justify-center gap-2 text-xs min-[900px]:hidden">
              <li className="border-mkt-line-soft flex items-center gap-1.5 rounded-full border bg-white px-3 py-1">
                <span aria-hidden className="bg-mkt-proof size-1.5 rounded-full" />
                Deterministic scoring
              </li>
              <li className="border-mkt-line-soft flex items-center gap-1.5 rounded-full border bg-white px-3 py-1">
                <span aria-hidden className="bg-mkt-evidence size-1.5 rounded-full" />
                Verified evidence
              </li>
              <li className="border-mkt-line-soft flex items-center gap-1.5 rounded-full border bg-white px-3 py-1">
                <span aria-hidden className="bg-mkt-proof-line size-1.5 rounded-full" />
                Encrypted keys
              </li>
            </ul>
          </div>
        </div>

        {/* Footer band */}
        <footer className="text-mkt-ink-muted text-xs">
          <span className="min-[900px]:hidden">© {new Date().getFullYear()} CUBE27</span>
        </footer>
      </main>
    </div>
  );
}
