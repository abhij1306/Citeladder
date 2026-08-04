import type { Metadata } from 'next';
import { Geist } from 'next/font/google';

import { QueryProvider } from '@/lib/providers/query-provider';
import { SITE_NAME, SITE_TAGLINE, siteOrigin } from '@/lib/seo/site';
import './globals.css';

const geist = Geist({
  subsets: ['latin'],
  variable: '--font-geist',
  display: 'swap',
});

const DIRECTION_CONTRACT = `<!--
THESIS: CiteLadder turns persisted AI evidence into the next measurable action; it refuses the metric-card gallery.
OWN-WORLD: Cool-white flat surfaces, structural hairlines, enterprise teal interaction, Geist UI type, and Apfel Grotezk identity type.
STORY: See project state, understand comparable movement, act on a ranked evidence-backed queue, then remeasure without causal overclaiming.
FIRST VIEWPORT: A sentence-led state header above a dominant movement chart and right-hand action queue; report and measurement actions sit with state.
FORM: Approved composition B, enriched with composition C queue detail; seed citeladder-command-center-b.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, and DESIGN.md
-->`;

export const metadata: Metadata = {
  // metadataBase is omitted until a canonical origin is configured (B3);
  // relative OG/canonical URLs are tolerated by Next in that state.
  metadataBase: siteOrigin() ?? undefined,
  title: {
    default: `${SITE_NAME} — ${SITE_TAGLINE}`,
    template: `%s · ${SITE_NAME}`,
  },
  description: 'AI visibility analytics — see how LLMs represent your brand.',
  applicationName: SITE_NAME,
  icons: { icon: '/icon.svg' },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={geist.variable}>
      <body>
        <span hidden dangerouslySetInnerHTML={{ __html: DIRECTION_CONTRACT }} />
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
