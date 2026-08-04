import type { Metadata } from 'next';

import { BlogIndex } from '@/components/marketing/pages/blog';

const DESCRIPTION =
  'Essays, release notes, and field reports on answer-engine optimization — ' +
  'evidence-first, and straight from the team building CiteLadder.';

// OG images require an absolute URL; they are added with NEXT_PUBLIC_SITE_URL (lib/seo/site.ts).
export const metadata: Metadata = {
  title: 'Blog — notes on AI visibility',
  description: DESCRIPTION,
  alternates: { canonical: '/blog' },
  openGraph: {
    title: 'Blog — notes on AI visibility',
    description: DESCRIPTION,
    type: 'website',
    siteName: 'CiteLadder',
  },
  twitter: {
    card: 'summary',
    title: 'Blog — notes on AI visibility',
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
    <main>
      <BlogIndex />
    </main>
  );
}
