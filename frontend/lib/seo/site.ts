import { getSiteUrl } from '@/lib/config/env';

/**
 * Canonical public origin, e.g. 'https://app.citeladder.com'. Unset in dev and
 * until the production domain is approved (owner blocker B3) — every consumer
 * degrades instead of guessing: `metadataBase` is omitted, canonicals stay
 * relative, `robots.ts` emits no `sitemap:` line, and the Organization JSON-LD
 * block is skipped. Validation mirrors the demo page's `safeBookingUrl`:
 * `new URL()` in a try, https-only, no credentials.
 */

export const SITE_NAME = 'CiteLadder';
export const SITE_TAGLINE = 'Evidence-grounded answer-engine growth';

/** Parses NEXT_PUBLIC_SITE_URL. Returns null when unset or not a clean https origin. */
export function siteOrigin(): URL | null {
  const value = getSiteUrl();
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password ? url : null;
  } catch {
    return null;
  }
}

/** Absolute URL for a site path, or null while no canonical origin is configured. */
export function absoluteUrl(path: string): string | null {
  const origin = siteOrigin();
  if (!origin) return null;
  return new URL(path, origin).toString();
}
