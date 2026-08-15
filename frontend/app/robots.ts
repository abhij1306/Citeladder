import type { MetadataRoute } from 'next';

import { absoluteUrl } from '@/lib/seo/site';

/**
 * The marketing surface is crawlable; the signed-in app is not. The disallow
 * list mirrors the app route groups (`app/(app)` + onboarding) and the API.
 * The `sitemap:` directive needs an absolute URL, so it is emitted only once
 * a canonical origin exists (B3) — the file is valid without it.
 */
export default function robots(): MetadataRoute.Robots {
  const sitemap = absoluteUrl('/sitemap.xml');
  return {
    rules: [
      {
        userAgent: '*',
        allow: '/',
        disallow: [
          '/api/',
          '/onboarding',
          '/visibility',
          '/ai-referrals',
          '/traffic',
          '/prompts',
          '/products',
          '/runs',
          '/content',
          '/site',
          '/issues',
          '/opportunities',
          '/projects',
          '/settings',
        ],
      },
    ],
    ...(sitemap ? { sitemap } : {}),
  };
}
