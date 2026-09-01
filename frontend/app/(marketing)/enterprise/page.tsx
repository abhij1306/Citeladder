import type { Metadata } from 'next';

import {
  EnterpriseContactCta,
  EnterpriseFit,
  EnterpriseHero,
  EnterpriseLimits,
  EnterpriseOps,
} from '@/components/marketing/pages/enterprise';
import { JsonLd } from '@/components/marketing/seo/json-ld';
import { absoluteUrl } from '@/lib/seo/site';

const DESCRIPTION =
  'CiteLadder Enterprise helps security-conscious teams measure AI visibility with a managed, ' +
  'workspace-scoped evidence trail, BYOK provider connections, deterministic analysis, and ' +
  'durable audit history.';
const ENTERPRISE_URL = absoluteUrl('/enterprise');

const ENTERPRISE_SERVICE_JSON_LD = {
  '@context': 'https://schema.org',
  '@type': 'Service',
  name: 'CiteLadder Enterprise',
  serviceType: 'AI visibility measurement',
  description: DESCRIPTION,
  ...(ENTERPRISE_URL ? { url: ENTERPRISE_URL } : {}),
  provider: { '@type': 'Organization', name: 'CiteLadder' },
} as const;

// OG images require an absolute URL; they are added with NEXT_PUBLIC_SITE_URL (lib/seo/site.ts).
export const metadata: Metadata = {
  title: 'Enterprise AI visibility measurement',
  description: DESCRIPTION,
  alternates: { canonical: '/enterprise' },
  openGraph: {
    title: 'Enterprise AI visibility measurement',
    description: DESCRIPTION,
    type: 'website',
    siteName: 'CiteLadder',
  },
  twitter: {
    card: 'summary',
    title: 'Enterprise AI visibility measurement',
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
    <main id="main">
      <JsonLd data={ENTERPRISE_SERVICE_JSON_LD} />
      <EnterpriseHero />
      <EnterpriseOps />
      <EnterpriseFit />
      <EnterpriseLimits />
      <EnterpriseContactCta />
    </main>
  );
}
