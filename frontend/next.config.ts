import withBundleAnalyzer from '@next/bundle-analyzer';
import type { NextConfig } from 'next';

/**
 * Next.js config — same-origin API proxy (F2).
 *
 * The browser must only ever call `/api/...` **relative** (invariant 12). The
 * `rewrites()` below proxy `/api/:path*` to the server-only `BACKEND_ORIGIN`
 * environment variable, so the backend URL never reaches the client bundle and
 * there is no cross-origin request (gotcha 2: a cross-origin backend behind a
 * tunnel double-sets `Access-Control-Allow-Origin`; the same-origin proxy
 * avoids that entirely).
 *
 * Environment:
 *   BACKEND_ORIGIN — REQUIRED, server-only. The absolute origin of the FastAPI
 *     backend, e.g. `http://localhost:8000` in local dev or the internal
 *     service URL in production. It is read only in `next.config.ts` (build /
 *     server), is NOT prefixed with `NEXT_PUBLIC_`, and is therefore never
 *     exposed to the browser. Defaults to `http://localhost:8000` for local dev;
 *     production builds fail closed when it is absent or points at loopback.
 */
/**
 * True for an IPv4-mapped IPv6 literal (`::ffff:7f00:1`, `::ffff:127.0.0.1`, or
 * the uncompressed `0:0:0:0:0:ffff:…`).
 *
 * These defeat a naive loopback check: `http://[::ffff:127.0.0.1]` is
 * normalized by `URL` to `[::ffff:7f00:1]`, which is neither `::1` nor prefixed
 * `127.`, so it slipped through. Rather than decode the embedded address and
 * test it for 127/8, reject EVERY mapped IPv4 literal — there is no legitimate
 * reason to express a backend origin that way, and enumerating which mapped
 * ranges are loopback is exactly the kind of check that gets one case wrong.
 *
 * Written as a segment walk rather than a regex: the natural pattern for the
 * optional-zero-groups prefix nests quantifiers and backtracks super-linearly.
 */
function isMappedIpv4Literal(host: string): boolean {
  if (!host.includes(':')) return false;
  const segments = host.split(':');
  const marker = segments.findIndex((segment) => segment === 'ffff');
  if (marker < 0) return false;
  // Everything before the `ffff` marker must be the 80 leading zero bits,
  // written either as empty (compressed) or explicit zero groups.
  return segments.slice(0, marker).every((segment) => segment === '' || /^0+$/.test(segment));
}

export function resolveBackendOrigin(
  configuredValue = process.env.BACKEND_ORIGIN,
  production = process.env.NODE_ENV === 'production',
) {
  const configured = configuredValue?.trim();
  if (!configured) {
    if (production) throw new Error('BACKEND_ORIGIN is required for a production build.');
    return 'http://localhost:8000';
  }

  let parsed: URL;
  try {
    parsed = new URL(configured);
  } catch {
    throw new Error('BACKEND_ORIGIN must be an absolute http(s) origin.');
  }
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) {
    throw new Error('BACKEND_ORIGIN must be a credential-free http(s) origin.');
  }
  if (parsed.pathname !== '/' || parsed.search || parsed.hash) {
    throw new Error('BACKEND_ORIGIN must not include a path, query, or fragment.');
  }
  // `URL` keeps IPv6 literals bracketed; strip them so one set of comparisons
  // covers both forms.
  const host = parsed.hostname
    .toLowerCase()
    .replace(/[.]+$/, '')
    .replace(/^\[|\]$/g, '');
  if (
    production &&
    (host === 'localhost' ||
      host === '0.0.0.0' ||
      host === '::' ||
      host === '::1' ||
      host.startsWith('127.') ||
      isMappedIpv4Literal(host))
  ) {
    throw new Error('BACKEND_ORIGIN must not use a loopback host in production.');
  }
  return parsed.origin;
}

const BACKEND_ORIGIN = resolveBackendOrigin();

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  // Next 16 blocks cross-origin requests to /_next/* dev resources. The app is
  // opened via 127.0.0.1 while the dev server treats `localhost` as canonical,
  // so allow the loopback IP or the browser gets a blank (unhydrated) page.
  // `**.vorflux.com` covers the Vorflux preview tunnels (multi-level
  // subdomains) so the shared public preview URL hydrates the same way.
  allowedDevOrigins: ['127.0.0.1', '**.vorflux.com'],
  // Brand-avatar fallback for sites that block our own crawler. `<BrandLogo>`
  // renders these `unoptimized`, so nothing is proxied through the Next image
  // optimizer — but the host must still be allowlisted for `next/image`.
  images: {
    remotePatterns: [{ protocol: 'https', hostname: 'img.logo.dev' }],
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${BACKEND_ORIGIN}/api/:path*`,
      },
    ];
  },
};

/**
 * Bundle analyzer, off unless `ANALYZE=true`.
 *
 * READ THIS BEFORE REACHING FOR IT: `@next/bundle-analyzer` is a webpack
 * plugin and Next 16 builds with Turbopack by default, so `ANALYZE=true pnpm
 * build` prints "not compatible with Turbopack builds, no report will be
 * generated" and writes nothing. Use `pnpm analyze` instead, which runs
 * Next's own Turbopack analyzer. This wrapper is kept because it is inert when
 * disabled and becomes correct the moment a build runs on webpack.
 *
 * Wraps only the DEFAULT export: `resolveBackendOrigin` above stays a plain
 * named export because `next.config.test.ts` imports it directly, and that
 * import executes this module — so the wrapper has to stay a no-op passthrough
 * when the flag is unset, which is exactly what `enabled: false` gives.
 */
export default withBundleAnalyzer({
  enabled: process.env.ANALYZE === 'true',
})(nextConfig);
