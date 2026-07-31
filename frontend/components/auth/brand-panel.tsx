import { FileSearch, Lock, Target } from 'lucide-react';
import Link from 'next/link';

import { Meta } from '@/components/marketing/primitives/label';
import { Wordmark } from '@/components/marketing/primitives/wordmark';
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
  {
    icon: Target,
    lead: 'Deterministic Scoring',
    description: 'Repeatable, objective AI search performance evaluation',
  },
  {
    icon: FileSearch,
    lead: 'Evidence For Every Metric',
    description: 'Trace ratings directly back to verified model outputs',
  },
  {
    icon: Lock,
    lead: 'Encrypted Key Vault',
    description: 'Your own API keys, fully encrypted with zero retention',
  },
] as const;

export function AuthWordmark({ compact = false }: Readonly<{ compact?: boolean }>) {
  return (
    <Link
      href="/"
      aria-label="Searchify home"
      className="group inline-flex items-center gap-3 no-underline"
    >
      <Wordmark className={cn(compact && 'text-mkt-body')} />
    </Link>
  );
}

export function AuthBrandPanel() {
  return (
    <div className="relative col-span-5 flex min-h-full flex-col justify-between px-12 py-12 max-[900px]:hidden xl:px-16">
      {/* Subtle light ambient glow */}
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="bg-mkt-proof-soft/40 absolute -top-24 -left-24 size-96 rounded-full blur-[100px]" />
        <div className="bg-mkt-sky/40 absolute top-1/2 -right-24 size-80 rounded-full blur-[90px]" />
      </div>

      <div className="flex flex-col gap-10">
        <div>
          <AuthWordmark />
        </div>

        {/* Feature showcase */}
        <div className="my-auto max-w-lg space-y-8">
          <div className="border-mkt-proof-line/50 bg-mkt-wash text-mkt-proof-hover inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold">
            <span className="relative flex size-2">
              <span className="bg-mkt-proof-line absolute inline-flex size-full animate-ping rounded-full opacity-75 motion-reduce:animate-none"></span>
              <span className="bg-mkt-proof relative inline-flex size-2 rounded-full"></span>
            </span>
            Enterprise AI Search Intelligence
          </div>

          <div className="space-y-3">
            <h2 className="font-mkt-display text-mkt-ink text-3xl leading-tight font-bold sm:text-4xl">
              See how AI models talk about your brand.
            </h2>
            <p className="text-mkt-ink-soft text-base leading-relaxed">
              Continuous, automated audits across ChatGPT, Gemini, and Claude with the real prompts
              your buyers ask.
            </p>
          </div>

          {/* Feature Cards - No separating lines */}
          <div className="grid gap-3 pt-2">
            {PROOF_POINTS.map((proof) => (
              <div
                key={proof.lead}
                className="group shadow-card border-mkt-line-soft hover:border-mkt-proof-line flex items-start gap-4 rounded-xl border bg-white p-4 transition-colors duration-200"
              >
                <div
                  aria-hidden
                  className="border-mkt-proof-line/30 bg-mkt-wash text-mkt-proof flex size-10 shrink-0 items-center justify-center rounded-lg border transition-transform duration-200 group-hover:scale-105"
                >
                  <proof.icon className="size-5" strokeWidth={1.75} />
                </div>
                <div className="space-y-0.5">
                  <p className="text-mkt-ink text-sm font-semibold">{proof.lead}</p>
                  <p className="text-mkt-ink-muted text-xs">{proof.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Footer info & active engine status */}
      <div className="text-mkt-ink-muted flex items-center justify-between pt-6 text-xs">
        <Meta as="p" className="text-mkt-ink-muted">
          © {new Date().getFullYear()} CUBE27
        </Meta>
        <div className="border-mkt-line-soft text-mkt-ink-soft flex items-center gap-2 rounded-full border bg-white px-3 py-1">
          <span className="bg-mkt-evidence size-1.5 animate-pulse rounded-full motion-reduce:animate-none" />
          <span>ChatGPT • Gemini • Claude Active</span>
        </div>
      </div>
    </div>
  );
}
