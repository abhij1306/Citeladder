import { ArrowRight, CalendarDays, Mail } from 'lucide-react';
import type { Metadata } from 'next';

import { ButtonLink } from '@/components/marketing/primitives/button';
import { PageHero } from '@/components/marketing/primitives/page-hero';
import { Section } from '@/components/marketing/primitives/section';
import {
  DEMO_CARDS,
  DEMO_HERO,
  DEMO_META,
  DEMO_SELF_SERVE_FALLBACK,
} from '@/lib/marketing-content/demo';

// OG images require an absolute URL; they are added with NEXT_PUBLIC_SITE_URL (lib/seo/site.ts).
export const metadata: Metadata = {
  title: DEMO_META.title,
  description: DEMO_META.description,
  alternates: { canonical: '/demo' },
  openGraph: {
    title: DEMO_META.title,
    description: DEMO_META.description,
    type: 'website',
    siteName: 'CiteLadder',
  },
  twitter: {
    card: 'summary',
    title: DEMO_META.title,
    description: DEMO_META.description,
  },
};

function safeBookingUrl(value: string | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password ? url.toString() : null;
  } catch {
    return null;
  }
}

/**
 * Public `/demo` — every primary CTA on the surface lands here, so all three
 * configuration states convert: an approved booking URL, a public sales
 * address, or neither (self-serve with a plain explanation). No contact
 * details are collected on this page in any state.
 */
export default function DemoPage() {
  const bookingUrl = safeBookingUrl(process.env.DEMO_BOOKING_URL);
  const salesEmail = process.env.PUBLIC_SALES_EMAIL?.trim();
  const actionHref = bookingUrl ?? (salesEmail ? `mailto:${salesEmail}` : null);

  return (
    <main>
      <PageHero
        centered
        eyebrow={DEMO_HERO.eyebrow}
        title={DEMO_HERO.title}
        accent={DEMO_HERO.accent}
        lead={DEMO_HERO.lead}
      >
        <div className="mt-8 flex flex-col items-center justify-center gap-4 sm:flex-row">
          {actionHref ? (
            <ButtonLink
              href={actionHref}
              target={bookingUrl ? '_blank' : undefined}
              rel={bookingUrl ? 'noreferrer' : undefined}
            >
              {bookingUrl ? (
                <CalendarDays className="size-4" aria-hidden />
              ) : (
                <Mail className="size-4" aria-hidden />
              )}
              {bookingUrl ? 'Schedule demo' : 'Email sales'}
              <ArrowRight aria-hidden />
            </ButtonLink>
          ) : (
            // No booking URL and no sales inbox configured: "Compare plans" IS
            // the action, so it takes the primary slot and the ghost step is
            // dropped. Rendering both left two links one gap apart with the
            // same accessible name and the same destination.
            <ButtonLink href="/pricing">
              Compare plans
              <ArrowRight aria-hidden />
            </ButtonLink>
          )}
          {actionHref && (
            <ButtonLink href="/pricing" variant="ghost">
              Compare plans
            </ButtonLink>
          )}
        </div>
        {!actionHref && (
          <p className="text-muted mx-auto mt-8 max-w-[80ch] text-sm">{DEMO_SELF_SERVE_FALLBACK}</p>
        )}
      </PageHero>

      <Section tone="paper" rhythm="tight" aria-label="What to expect">
        <div className="mx-auto grid max-w-4xl gap-5 md:grid-cols-3">
          {DEMO_CARDS.map(([title, description]) => (
            <section
              key={title}
              className="border-border-subtle bg-background rounded-lg border p-8"
            >
              <h2 className="font-display text-foreground text-xl">{title}</h2>
              <p className="text-muted mt-3 text-sm">{description}</p>
            </section>
          ))}
        </div>
        <p className="text-muted mx-auto mt-8 max-w-5xl text-center text-sm">
          CiteLadder does not store demo-lead details on this page. If scheduling is enabled, the
          approved booking provider’s privacy terms apply at the external destination.
        </p>
      </Section>
    </main>
  );
}
