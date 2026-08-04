import type { Metadata } from 'next';

import {
  EnterpriseContactCta,
  EnterpriseHero,
  EnterpriseLimits,
  EnterpriseOps,
} from '@/components/marketing/pages/enterprise';

const DESCRIPTION =
  'Enterprise CiteLadder: deterministic, auditable AI-visibility scoring over immutable, ' +
  'provenance-carrying evidence. BYOK with Fernet-encrypted write-only keys, UUID workspace ' +
  'isolation, PostgreSQL-durable queues — operated as managed cloud with a security review ' +
  'and a named contact.';

// OG images require an absolute URL; they are added with NEXT_PUBLIC_SITE_URL (lib/seo/site.ts).
export const metadata: Metadata = {
  title: 'Enterprise — AI visibility with enterprise-grade evidence',
  description: DESCRIPTION,
  alternates: { canonical: '/enterprise' },
  openGraph: {
    title: 'Enterprise — AI visibility with enterprise-grade evidence',
    description: DESCRIPTION,
    type: 'website',
    siteName: 'CiteLadder',
  },
  twitter: {
    card: 'summary',
    title: 'Enterprise — AI visibility with enterprise-grade evidence',
    description: DESCRIPTION,
  },
};

/**
 * Public marketing `/enterprise` page. Server-rendered so the full page is in
 * the initial HTML (SEO + first paint); renders no client islands of its own.
 * The shared chrome (aurora/grain backdrop, LandingNav, LandingFooter) lives
 * in the (marketing) route-group layout.
 *
 * Must stay a SYNC component (no async / headers() / cookies()) so the page
 * test can render it directly under Testing Library.
 */
export default function EnterprisePage() {
  return (
    <main>
      <EnterpriseHero />
      <EnterpriseOps />
      <EnterpriseLimits />
      <EnterpriseContactCta />
    </main>
  );
}
