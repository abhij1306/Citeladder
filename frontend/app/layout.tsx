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
THESIS: Account access and project setup are one calm guided flow; it refuses the decorative split-screen rail and nested setup cards.
OWN-WORLD: light neutral ground, crisp hairlines, Plus Jakarta Sans display with Geist body, 12px controls, quiet selected answers, and cobalt reserved for the current step and primary action.
STORY: Enter the essential site facts, watch evidence resolve, confirm exactly what will be tracked, then create the project.
FIRST VIEWPORT: A 64px wordmark and progress bar frame one centred 720px column; the scrolling task sits above a persistent action bar, with review widening only to 880px.
FORM: centred guided flow, code-led, seed key user-locked-one-flow-four-screens.
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
