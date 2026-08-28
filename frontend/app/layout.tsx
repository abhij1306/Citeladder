import type { Metadata } from 'next';
import { Geist, Plus_Jakarta_Sans } from 'next/font/google';

import { QueryProvider } from '@/lib/providers/query-provider';
import { SITE_NAME, SITE_TAGLINE, siteOrigin } from '@/lib/seo/site';
import './globals.css';

const geist = Geist({
  subsets: ['latin'],
  variable: '--font-geist',
  display: 'swap',
});

const plusJakartaSans = Plus_Jakarta_Sans({
  subsets: ['latin'],
  variable: '--font-plus-jakarta-sans',
  display: 'swap',
});

const DIRECTION_CONTRACT = `<!--
THESIS: CiteLadder turns persisted AI evidence into the next measurable action; it refuses the metric-card gallery.
OWN-WORLD: refined light system — white surfaces, neutral-gray highlights, one reference-blue accent, soft crisp elevation, Plus Jakarta Sans website display + Geist UI, and a 16px website reading baseline.
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
  icons: { icon: '/citeladder-favicon.ico' },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${geist.variable} ${plusJakartaSans.variable}`}>
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
