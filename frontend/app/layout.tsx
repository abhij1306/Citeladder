import type { Metadata } from 'next';
import { Google_Sans, Plus_Jakarta_Sans } from 'next/font/google';

import { QueryProvider } from '@/lib/providers/query-provider';
import { SITE_NAME, SITE_TAGLINE, siteOrigin } from '@/lib/seo/site';
import { THEME_BOOTSTRAP_SCRIPT } from '@/lib/theme';

import './globals.css';

// Two faces total: Google Sans for UI, body, and data (no monospace is
// shipped; numeric contexts use Google Sans with tabular-nums), and Plus
// Jakarta Sans for headings/display across both the app and the marketing
// site. No other family is loaded anywhere.
const sans = Google_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-google-sans',
  display: 'swap',
});

const display = Plus_Jakarta_Sans({
  subsets: ['latin'],
  weight: ['500', '600'],
  variable: '--font-jakarta',
  display: 'swap',
});

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
    <html lang="en" suppressHydrationWarning className={`${sans.variable} ${display.variable}`}>
      <head>
        {/* Pre-hydration theme bootstrap — sets data-theme before first paint
            to avoid a flash (see lib/theme.ts). Must run before hydration. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }} />
      </head>
      <body>
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
