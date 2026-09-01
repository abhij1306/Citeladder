import type { MetadataRoute } from 'next';

import { POSTS } from '@/lib/marketing-content/blog';
import { COMPETITORS } from '@/lib/marketing-content/compare';
import { absoluteUrl } from '@/lib/seo/site';

/**
 * Public-surface sitemap: indexable marketing routes, then one entry per
 * published post and comparison — both
 * enumerated from their content modules, so the sitemap grows with the
 * content. While no canonical origin is configured (B3) entries are
 * path-only; Next tolerates that and the file stays valid.
 */

type RouteEntry = {
  path: string;
  changeFrequency: NonNullable<MetadataRoute.Sitemap[number]['changeFrequency']>;
  priority: number;
};

const STATIC_ROUTES: readonly RouteEntry[] = [
  { path: '/', changeFrequency: 'weekly', priority: 1 },
  { path: '/pricing', changeFrequency: 'monthly', priority: 0.9 },
  { path: '/enterprise', changeFrequency: 'monthly', priority: 0.8 },
  { path: '/solutions', changeFrequency: 'monthly', priority: 0.8 },
  { path: '/demo', changeFrequency: 'monthly', priority: 0.7 },
  { path: '/faq', changeFrequency: 'monthly', priority: 0.6 },
  { path: '/blog', changeFrequency: 'weekly', priority: 0.6 },
  { path: '/compare', changeFrequency: 'monthly', priority: 0.6 },
];

function entry({ path, changeFrequency, priority }: RouteEntry): MetadataRoute.Sitemap[number] {
  return {
    url: absoluteUrl(path) ?? path,
    changeFrequency,
    priority,
  };
}

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    ...STATIC_ROUTES.map(entry),
    ...POSTS.map((post) =>
      entry({
        path: `/blog/${post.slug}`,
        changeFrequency: 'yearly',
        priority: 0.7,
      }),
    ),
    ...COMPETITORS.map((competitor) =>
      entry({
        path: `/compare/${competitor.slug}`,
        changeFrequency: 'monthly',
        priority: 0.5,
      }),
    ),
  ];
}
