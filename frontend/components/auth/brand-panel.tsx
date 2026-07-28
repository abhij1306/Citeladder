import { FileSearch, Lock, Target } from 'lucide-react';
import Link from 'next/link';

import { Meta } from '@/components/marketing/primitives/label';
import { Wordmark } from '@/components/marketing/primitives/wordmark';
import { WallpaperPanel } from '@/components/marketing/scenes/wallpaper-panel';
import { cn } from '@/lib/utils';

/**
 * Auth brand panel — the left column of the split-screen auth shell, on the
 * Proof surface.
 *
 * Deliberately free of product screenshots and sample dashboards: an
 * unauthenticated visitor has no data, and inventing a fictional workspace to
 * decorate a sign-in page would misrepresent the product. The panel states
 * what Searchify does and how it treats your keys, and stops there.
 *
 * The proof points are labels, not paragraphs. Nobody reads a methodology
 * note while trying to log in, and the marketing site makes the argument at
 * length — three short lines carry the same reassurance and let the headline
 * breathe.
 *
 * Hidden below 900px, where the form column renders <AuthWordmark compact>
 * above the form instead.
 *
 * The single-h1 rule: the auth pages own the only h1 — the wordmarks here are
 * spans, and the brand headline is a `<p>`.
 */
const PROOF_POINTS = [
  { icon: Target, lead: 'Deterministic scoring' },
  { icon: FileSearch, lead: 'Evidence for every number' },
  { icon: Lock, lead: 'Your own API keys, encrypted' },
] as const;

export function AuthWordmark({ compact = false }: Readonly<{ compact?: boolean }>) {
  return (
    <Link href="/" aria-label="Searchify home" className="inline-flex no-underline">
      <Wordmark className={cn(compact && 'text-mkt-body')} />
    </Link>
  );
}

export function AuthBrandPanel() {
  return (
    <WallpaperPanel
      rounded={false}
      className="relative col-span-5 flex flex-col border-0 border-r px-10 py-8 max-[900px]:hidden xl:px-12"
    >
      <div className="relative z-1 flex min-h-full flex-1 flex-col">
        <AuthWordmark />

        {/* Centred body — the same three-band rhythm as the form column, so
            the headline sits on the form's optical centre line. No floating
            card: the panel IS the surface, so the statement sets directly on
            the wallpaper at display scale and the proof points hang as a flat
            ruled list underneath. */}
        <div className="flex flex-1 items-center py-12">
          <div className="max-w-[30rem]">
            <p className="font-mkt-display text-mkt-d2 text-mkt-ink font-medium">
              See how AI answers talk about your brand.
            </p>
            <p className="text-mkt-lead text-mkt-ink-soft mt-4 max-w-[26rem]">
              Audits ChatGPT, Gemini and Claude with the prompts your buyers ask.
            </p>

            <ul className="border-mkt-line mt-10 grid list-none gap-0 border-t p-0">
              {PROOF_POINTS.map((proof) => (
                <li
                  key={proof.lead}
                  className="border-mkt-line flex items-center gap-3 border-b py-3"
                >
                  <span
                    aria-hidden
                    className="border-mkt-proof-line bg-mkt-wash text-mkt-proof flex size-8 shrink-0 items-center justify-center rounded-sm border"
                  >
                    <proof.icon className="size-4" strokeWidth={1.75} />
                  </span>
                  <span className="text-mkt-body text-mkt-ink">{proof.lead}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <Meta as="p" className="text-mkt-ink-muted">
          © {new Date().getFullYear()} CUBE27
        </Meta>
      </div>
    </WallpaperPanel>
  );
}
