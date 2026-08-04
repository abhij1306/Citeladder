import type { Metadata } from 'next';

import { PricingCta } from '@/components/marketing/pages/pricing';
import { PricingCatalog } from '@/components/marketing/pricing/pricing-catalog';
import { PageHero } from '@/components/marketing/primitives/page-hero';
import { TrustStrip } from '@/components/marketing/primitives/trust-strip';

// No amount appears in this metadata. Prices are region-resolved by the server
// per visitor, so a number baked into a static description would be wrong for
// most of them and would go stale the moment the catalog changed.
const DESCRIPTION =
  'Pricing for CiteLadder, the AI visibility and site intelligence platform: ' +
  'self-serve plans plus a sales-assisted Enterprise agreement. Audits run on your own ' +
  'provider keys. India is billed in INR with GST added; international cards are charged in USD.';

// OG images require an absolute URL; they are added with NEXT_PUBLIC_SITE_URL (lib/seo/site.ts).
export const metadata: Metadata = {
  title: 'Pricing — BYOK AI visibility audits, site health & AEO monitoring',
  description: DESCRIPTION,
  alternates: { canonical: '/pricing' },
  openGraph: {
    title: 'Pricing — BYOK AI visibility audits, site health & AEO monitoring',
    description: DESCRIPTION,
    type: 'website',
    siteName: 'CiteLadder',
  },
  twitter: {
    card: 'summary',
    title: 'Pricing — BYOK AI visibility audits, site health & AEO monitoring',
    description: DESCRIPTION,
  },
};

/**
 * Public pricing page (`/pricing`).
 *
 * Stays a SYNC server component (no async / headers() / cookies()) so the page
 * test can render it directly under Testing Library, and so the hero and
 * closing band arrive as server-rendered HTML. The catalog-backed plans are a
 * client island because every enforceable value is read from
 * `GET /billing/catalog` at request time — the trade is that the cards render
 * a loading shell until hydration rather than arriving pre-filled, which is
 * the cost of never shipping a price this page cannot stand behind.
 */
export default function PricingPage() {
  return (
    <main>
      <PageHero
        centered
        eyebrow="Pricing"
        title="Pay for the evidence layer."
        accent="Not the API markup."
        lead="Audits run on your own ChatGPT, Gemini and Claude keys — provider usage bills straight to your accounts at provider rates. CiteLadder charges for the workspace, the monitoring and the evidence behind every score."
      >
        <TrustStrip className="mt-8 justify-center" />
      </PageHero>
      <PricingCatalog />
      <PricingCta />
    </main>
  );
}
