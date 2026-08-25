import type { MetadataRoute } from 'next';

import { SITE_NAME, SITE_TAGLINE } from '@/lib/seo/site';

/**
 * Web app manifest. `theme_color`/`background_color` are deliberately absent:
 * they need literal hex values, which the design-token guard forbids outside
 * the token layer — a manifest without them is valid, so there is nothing to
 * work around.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: SITE_NAME,
    short_name: SITE_NAME,
    description: SITE_TAGLINE,
    start_url: '/',
    display: 'standalone',
    icons: [{ src: '/citeladder-favicon.ico', type: 'image/x-icon', sizes: '256x256' }],
  };
}
