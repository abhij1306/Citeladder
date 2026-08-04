import type { Metadata } from 'next';

import { FaqGroups } from '@/components/marketing/pages/faq';
import { PageHero } from '@/components/marketing/primitives/page-hero';
import { JsonLd } from '@/components/marketing/seo/json-ld';
import { faqPageJsonLd } from '@/lib/seo/json-ld';
import { FAQ_GROUPS } from '@/lib/marketing-content/faq';

const DESCRIPTION =
  'The short version of how CiteLadder works — engines, scoring, keys, site health, ' +
  'integrations, and billing.';

// OG images require an absolute URL; they are added with NEXT_PUBLIC_SITE_URL (lib/seo/site.ts).
export const metadata: Metadata = {
  title: 'FAQ',
  description: DESCRIPTION,
  alternates: { canonical: '/faq' },
  openGraph: {
    title: 'FAQ',
    description: DESCRIPTION,
    type: 'website',
    siteName: 'CiteLadder',
  },
  twitter: {
    card: 'summary',
    title: 'FAQ',
    description: DESCRIPTION,
  },
};

/**
 * Public FAQ page (`/faq`). Server-rendered; the accordion is native
 * <details>/<summary>, so the page ships zero client islands.
 *
 * Must stay a SYNC component (no async / headers() / cookies()) so the page
 * test can render it directly under Testing Library.
 */
export default function FaqPage() {
  return (
    <main>
      <JsonLd data={faqPageJsonLd(FAQ_GROUPS)} />
      <PageHero
        centered
        eyebrow="FAQ"
        title="Frequently asked"
        accent="questions."
        lead="The short version of how CiteLadder works — engines, scoring, keys, site health, integrations, and billing."
      />
      <FaqGroups />
    </main>
  );
}
