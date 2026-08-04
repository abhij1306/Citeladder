import type { ReactNode } from 'react';

import { MarketingFooter } from '@/components/marketing/chrome/footer';
import { MarketingNav } from '@/components/marketing/chrome/nav';
import { JsonLd } from '@/components/marketing/seo/json-ld';
import { BrandAtmosphere } from '@/components/ui/brand-atmosphere';
import { organizationJsonLd } from '@/lib/seo/json-ld';

/**
 * Marketing route-group layout — the public "Proof" surface.
 *
 * Deliberately NOT wrapped in SessionGuard: these pages must be reachable and
 * server-rendered for anonymous visitors.
 *
 * `.citeladder-root` is the one hook the creative system needs (see
 * app/(marketing)/marketing-theme.css): it scopes the light-only canvas and
 * the focus ring. Everything else is built from citeladder-namespaced utilities —
 * there is no marketing stylesheet to keep in sync.
 *
 * No fonts are loaded here: the root layout provides Geist and globals.css
 * self-hosts Apfel Grotezk, so --font-display is already in scope.
 */
export default function MarketingLayout({ children }: Readonly<{ children: ReactNode }>) {
  // Omitted while no canonical origin exists (B3) — Organization without url
  // is not worth emitting.
  const organization = organizationJsonLd();
  return (
    <div className="citeladder-root bg-background text-foreground relative isolate min-h-dvh">
      {organization ? <JsonLd data={organization} /> : null}
      <BrandAtmosphere variant="site" />
      <MarketingNav />
      <div className="relative z-1 pt-16">{children}</div>
      <div className="relative z-1">
        <MarketingFooter />
      </div>
    </div>
  );
}
