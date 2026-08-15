import type { Metadata } from 'next';
import localFont from 'next/font/local';

import { QueryProvider } from '@/lib/providers/query-provider';
import { SITE_NAME, SITE_TAGLINE, siteOrigin } from '@/lib/seo/site';
import './globals.css';

const switzer = localFont({
  src: [
    {
      path: './fonts/Switzer-Variable.woff2',
      weight: '100 900',
      style: 'normal',
    },
    {
      path: './fonts/Switzer-VariableItalic.woff2',
      weight: '100 900',
      style: 'italic',
    },
  ],
  variable: '--font-switzer',
  display: 'swap',
  fallback: ['Arial', 'sans-serif'],
});

const satoshi = localFont({
  src: './fonts/Satoshi-Variable.woff2',
  weight: '300 900',
  style: 'normal',
  variable: '--font-satoshi',
  display: 'swap',
  fallback: ['Arial', 'sans-serif'],
});

const DIRECTION_CONTRACT = `<!--
THESIS: CiteLadder turns persisted AI evidence into the next measurable action; it refuses the metric-card gallery.
OWN-WORLD: refined light system — white surfaces, neutral-gray highlights, one reference-blue accent, soft crisp elevation, Satoshi display + Switzer UI, and a 16px website reading baseline.
STORY: See project state, understand comparable movement, act on a ranked evidence-backed queue, then remeasure without causal overclaiming.
FIRST VIEWPORT: A sentence-led state header above a dominant movement chart and right-hand action queue; report and measurement actions sit with state.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, and docs/design.md
-->`;

export const metadata: Metadata = {
  // metadataBase is omitted until a canonical origin is configured (B3);
  // relative OG/canonical URLs are tolerated by Next in that state.
  metadataBase: siteOrigin() ?? undefined,
  title: {
    default: `${SITE_NAME} — ${SITE_TAGLINE}`,
    template: `%s · ${SITE_NAME}`,
  },
  description:
    'Connect site and demand evidence, act on grounded opportunities, and track observed answer-engine citation share.',
  applicationName: SITE_NAME,
  icons: { icon: '/icon.svg' },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${switzer.variable} ${satoshi.variable}`}>
      <body>
        <span hidden dangerouslySetInnerHTML={{ __html: DIRECTION_CONTRACT }} />
        {/* First tab stop on every route. Visually hidden until focused, so
            keyboard and screen-reader users can skip repeated chrome. Each
            layout marks its own landmark with `id="main"`. */}
        <a href="#main" className="skip-link">
          Skip to main content
        </a>
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
