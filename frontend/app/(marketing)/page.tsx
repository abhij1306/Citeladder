import type { Metadata } from 'next';

import { FinalCta } from '@/components/marketing/landing/final-cta';
import { Hero } from '@/components/marketing/landing/hero';
import { Proof } from '@/components/marketing/landing/proof';
import { SeeIt } from '@/components/marketing/landing/see-it';
import { Shift } from '@/components/marketing/landing/shift';
import { WhatWeMeasure } from '@/components/marketing/landing/what-we-measure';
import { LandingSessionRedirect } from '@/components/marketing/landing-session-redirect';

const DESCRIPTION =
  'CiteLadder observes how the major answer engines describe your brand, products and ' +
  'competitors, traces every conclusion back to the answer it came from, and turns the ' +
  'pattern into strategy. Runs on your own provider keys, encrypted at rest.';

// OG images require an absolute URL; they are added with NEXT_PUBLIC_SITE_URL (lib/seo/site.ts).
export const metadata: Metadata = {
  // Absolute title: the root template must not append to the landing title.
  title: { absolute: 'CiteLadder — See your market through AI’s eyes' },
  description: DESCRIPTION,
  alternates: { canonical: '/' },
  openGraph: {
    title: 'CiteLadder — See your market through AI’s eyes',
    description: DESCRIPTION,
    type: 'website',
    siteName: 'CiteLadder',
  },
  twitter: {
    card: 'summary',
    title: 'CiteLadder — See your market through AI’s eyes',
    description: DESCRIPTION,
  },
};

/**
 * Public marketing landing page (`/`) on the Proof surface. Server-rendered so
 * the full page is in the initial HTML (SEO + first paint); the only client
 * island the page renders is the invisible LandingSessionRedirect, which
 * forwards signed-in visitors to their dashboard (`/projects`) or to
 * first-run `/onboarding` — the contract `/` had before this page existed.
 *
 * Six beats, in order: the hook (Hero), why the ground moved (Shift), the
 * product itself (SeeIt), what its numbers actually mean (WhatWeMeasure), how
 * they are verified (Proof), and the close (FinalCta). The measurement
 * disclosure sits before Proof deliberately — the axes have to be defined
 * before the verification story leans on them. Shared chrome (nav + footer) lives in the (marketing) route-group
 * layout.
 *
 * Must stay a SYNC component (no async / headers() / cookies()) so the page
 * test can render it directly under Testing Library.
 */
export default function LandingPage() {
  return (
    <LandingSessionRedirect>
      <main>
        <Hero />
        <Shift />
        <SeeIt />
        <WhatWeMeasure />
        <Proof />
        <FinalCta />
      </main>
    </LandingSessionRedirect>
  );
}
