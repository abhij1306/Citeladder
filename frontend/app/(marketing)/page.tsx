import type { Metadata } from 'next';

import { EvidenceChain } from '@/components/marketing/landing/evidence-chain';
import { FinalCta } from '@/components/marketing/landing/final-cta';
import { Hero } from '@/components/marketing/landing/hero';
import { Packs } from '@/components/marketing/landing/packs';
import { Platform } from '@/components/marketing/landing/platform';
import { SeeIt } from '@/components/marketing/landing/see-it';
import { Shift } from '@/components/marketing/landing/shift';
import { Trust } from '@/components/marketing/landing/trust';
import { Workflow } from '@/components/marketing/landing/workflow';
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
 * Nine beats, in order: the hook (Hero), why growth changed (Shift), how the
 * loop runs (Workflow), the four intelligence layers (Platform), the product
 * itself (SeeIt), the evidence chain and a real insight (EvidenceChain), who it
 * is shaped for (Packs), the data promise (Trust), and the close (FinalCta).
 * Shared chrome (nav + footer) lives in the (marketing) route-group layout.
 *
 * Workflow leads Platform deliberately: the differentiator is the loop
 * evidence → improvement → verification, and the module breakdown is HOW
 * rather than WHY (frontend-growth-intelligence.md §8.2). Bands alternate
 * paper/sunken with no two adjacent sections sharing a tone, which is why
 * EvidenceChain is sunken.
 *
 * Must stay a SYNC component (no async / headers() / cookies()) so the page
 * test can render it directly under Testing Library.
 */
export default function LandingPage() {
  return (
    <LandingSessionRedirect>
      <main id="main">
        <Hero />
        <Shift />
        <Workflow />
        <Platform />
        <SeeIt />
        <EvidenceChain />
        <Packs />
        <Trust />
        <FinalCta />
      </main>
    </LandingSessionRedirect>
  );
}
