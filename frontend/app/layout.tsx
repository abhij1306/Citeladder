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
THESIS: Prism Evidence is one calm editorial system from first visit through the operating workspace.
OWN-WORLD: warm neutral ground, navy ink and actions, indigo selection and focus, crisp hairlines, Plus Jakarta Sans editorial display with Geist body, and shadows reserved for floating UI.
STORY: Understand the evidence loop, evaluate the product, enter the essential site facts, confirm exactly what will be tracked, then operate from persisted evidence.
FIRST VIEWPORT: Public pages use generous editorial rhythm and faithful product scenes; focused flows use a compact wordmark bar, centred task column, and persistent action bar.
FORM: shared semantic tokens, flat ledgers and tonal compositions, with a roomier public/focused-flow type ladder over the same visual world.
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
