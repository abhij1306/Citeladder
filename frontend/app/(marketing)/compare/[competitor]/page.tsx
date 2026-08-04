import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { CompareDetailView } from '@/components/marketing/pages/compare-detail';
import { COMPETITORS, type Competitor } from '@/lib/marketing-content/compare';

type PageParams = { competitor: string };

/** Every comparison in the module prerenders at build time (SSG). */
export function generateStaticParams(): PageParams[] {
  return COMPETITORS.map((competitor) => ({ competitor: competitor.slug }));
}

function findCompetitor(slug: string): Competitor | undefined {
  return COMPETITORS.find((competitor) => competitor.slug === slug);
}

// OG images require an absolute URL; they are added with NEXT_PUBLIC_SITE_URL (lib/seo/site.ts).
export async function generateMetadata({
  params,
}: Readonly<{ params: Promise<PageParams> }>): Promise<Metadata> {
  const { competitor: slug } = await params;
  const competitor = findCompetitor(slug);
  if (!competitor) {
    return { title: 'Comparison not found' };
  }
  // Absolute title: the 'CiteLadder vs X' phrasing stands on its own — the root
  // template would only duplicate the brand.
  const title = `CiteLadder vs ${competitor.name}`;
  const description =
    `How CiteLadder compares to ${competitor.name}: engines covered, scoring model, evidence ` +
    'drill-down, BYOK privacy, and site-health auditing. The CiteLadder column is ' +
    `sourced from our source code. Last reviewed ${competitor.lastReviewed}.`;
  return {
    title: { absolute: title },
    description,
    alternates: { canonical: `/compare/${competitor.slug}` },
    openGraph: {
      title,
      description,
      type: 'website',
      siteName: 'CiteLadder',
    },
    twitter: {
      card: 'summary',
      title,
      description,
    },
  };
}

/**
 * Comparison detail (`/compare/[competitor]`) — the single allowed sync-RSC
 * exception alongside /blog/[slug]: Next 16's `params` is a Promise, so the
 * route's default export is a thin async wrapper that resolves the slug
 * (404 for unknown slugs) and hands the module entry to the sync
 * CompareDetailView, which is what the RTL tests render directly.
 */
export default async function CompareDetailPage({
  params,
}: Readonly<{ params: Promise<PageParams> }>) {
  const { competitor: slug } = await params;
  const competitor = findCompetitor(slug);
  if (!competitor) {
    notFound();
  }
  return (
    <main>
      <CompareDetailView competitor={competitor} />
    </main>
  );
}
