import type { Metadata } from 'next';

import { BlogIndex } from '@/components/marketing/pages/blog';

const DESCRIPTION =
  'Practical resources on answer-engine optimization, AI visibility measurement, provenance, ' +
  'and the evidence-led work between a finding and the next audit.';

// OG images require an absolute URL; they are added with NEXT_PUBLIC_SITE_URL (lib/seo/site.ts).
export const metadata: Metadata = {
  title: 'AEO & AI visibility resources',
  description: DESCRIPTION,
  keywords: ['AEO', 'answer-engine optimization', 'AI visibility', 'content evidence'],
  alternates: { canonical: '/blog' },
  openGraph: {
    title: 'AEO & AI visibility resources',
    description: DESCRIPTION,
    type: 'website',
    siteName: 'CiteLadder',
  },
  twitter: {
    card: 'summary',
    title: 'AEO & AI visibility resources',
    description: DESCRIPTION,
  },
};

/**
 * Public marketing blog index (`/blog`). Server-rendered so the full page is
 * in the initial HTML (SEO + first paint); the shared chrome (aurora/grain
 * backdrop, LandingNav, LandingFooter) comes from the (marketing) route-group
 * layout. Content renders from lib/marketing-content/blog (single import
 * site): featured-post slot for the first post, a card grid for the rest, or
 * the empty state when the posts array is empty.
 *
 * Must stay a SYNC component (no async / headers() / cookies()) so the page
 * test can render it directly under Testing Library.
 */
export default function BlogPage() {
  return (
    <main id="main">
      <BlogIndex />
    </main>
  );
}
