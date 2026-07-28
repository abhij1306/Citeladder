import type { ReactNode } from 'react';

import { MarketingFooter } from '@/components/marketing/chrome/footer';
import { MarketingNav } from '@/components/marketing/chrome/nav';
import { JsonLd, organizationJsonLd } from '@/components/marketing/seo/json-ld';

/**
 * Marketing route-group layout — the public "Proof" surface.
 *
 * Deliberately NOT wrapped in SessionGuard: these pages must be reachable and
 * server-rendered for anonymous visitors.
 *
 * `.mkt-root` is the one hook the creative system needs (see
 * app/(marketing)/marketing-theme.css): it scopes the light-only canvas and
 * the focus ring. Everything else is built from mkt-namespaced utilities —
 * there is no marketing stylesheet to keep in sync.
 *
 * No fonts are loaded here: the root layout puts Google Sans and Plus Jakarta
 * Sans on <html>, so --font-mkt-display (a Plus Jakarta Sans alias) is already
 * in scope.
 */
export default function MarketingLayout({ children }: Readonly<{ children: ReactNode }>) {
  // Omitted while no canonical origin exists (B3) — Organization without url
  // is not worth emitting.
  const organization = organizationJsonLd();
  return (
    <div className="mkt-root bg-mkt-paper text-mkt-ink min-h-dvh">
      {organization ? <JsonLd data={organization} /> : null}
      <MarketingNav />
      {/* Clears the fixed nav strip. Every page starts from the same line. */}
      <div className="pt-mkt-nav">{children}</div>
      <MarketingFooter />
    </div>
  );
}
