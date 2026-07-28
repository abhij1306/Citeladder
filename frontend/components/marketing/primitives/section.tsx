import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

import { Reveal } from './reveal';

/**
 * Vertical rhythm for the whole Proof surface. Sections NEVER set their own
 * top/bottom padding — the three densities live here, so every page on the
 * marketing/auth surface breathes identically. This is the single reason the
 * deck's per-section padding values (112 / 64 / 58 / 42 …) collapse into a
 * system instead of drifting page by page.
 *
 *   loose   128 / 80   — chapter openers, the hero's neighbours
 *   base     96 / 64   — the default
 *   tight    80 / 48   — bands that sit directly against another band
 */
const RHYTHM = {
  loose: 'py-20 md:py-32',
  base: 'py-16 md:py-24',
  tight: 'py-12 md:py-20',
} as const;

type Rhythm = keyof typeof RHYTHM;

/**
 * Band fills. Pages read as a rhythm of alternating bands rather than one
 * long sheet; the steps are deliberately small (ΔE2000 vs paper noted per
 * tone) so a band change registers without reading as a new page. The rule
 * is NO TWO ADJACENT BANDS SHARE A TONE — and where the tone changes, the
 * fill edge is the separator, so `divided` is only kept on same-tone
 * adjacency (a hairline on a fill edge reads as a double rule).
 */
const TONE = {
  paper: '', // the .mkt-root canvas, inherited
  surface: 'bg-mkt-surface', // ΔE 3.32 vs paper
  sunken: 'bg-mkt-surface-sunk', // ΔE 3.21 vs paper
  wash: 'bg-mkt-wash', // ΔE 7.12 vs paper, the accent beat
} as const;

type Tone = keyof typeof TONE;

type SectionProps = Readonly<{
  children: ReactNode;
  /** Vertical density (default `base`). */
  rhythm?: Rhythm;
  /** Band fill (default `paper` — the bare canvas). */
  tone?: Tone;
  /** Hairline rule above the section — only for same-tone adjacency. */
  divided?: boolean;
  /** Full-bleed content: skips the container so the child owns its width. */
  bleed?: boolean;
  id?: string;
  className?: string;
  'aria-label'?: string;
  'aria-labelledby'?: string;
}>;

export function Section({
  children,
  rhythm = 'base',
  tone = 'paper',
  divided = false,
  bleed = false,
  id,
  className,
  ...aria
}: SectionProps) {
  return (
    <section
      id={id}
      className={cn(
        TONE[tone],
        RHYTHM[rhythm],
        divided && 'border-mkt-line-soft border-t',
        className,
      )}
      {...aria}
    >
      {bleed ? children : <Container>{children}</Container>}
    </section>
  );
}

/**
 * One container and one gutter for the entire surface, so the wordmark in the
 * nav sits on the same optical line as every heading below it.
 */
export function Container({
  children,
  wide = false,
  className,
}: Readonly<{ children: ReactNode; wide?: boolean; className?: string }>) {
  return (
    <div
      className={cn(
        'px-mkt-gutter mx-auto w-full',
        wide ? 'max-w-mkt-wide' : 'max-w-mkt',
        className,
      )}
    >
      {children}
    </div>
  );
}

/**
 * The deck's chapter opener: a numbered rail, the display heading, and a
 * standfirst that stays out of the heading's measure. Collapses to a single
 * column below `lg` rather than keeping a cramped three-column grid.
 */
export function SectionHeader({
  index,
  kicker,
  title,
  intro,
  headingId,
  as: Heading = 'h2',
}: Readonly<{
  /** Chapter number, e.g. `01`. Rendered with the kicker as `01 / NORTH STAR`. */
  index?: string;
  kicker?: string;
  title: ReactNode;
  intro?: ReactNode;
  headingId?: string;
  as?: 'h1' | 'h2' | 'h3';
}>) {
  return (
    <Reveal className="mb-12 grid items-start gap-x-8 gap-y-5 lg:mb-16 lg:grid-cols-[7.5rem_minmax(0,1fr)_20rem]">
      {(index ?? kicker) && (
        <p className="text-mkt-meta text-mkt-ink-soft pt-2 font-mono uppercase tabular-nums lg:pt-3">
          {[index, kicker].filter(Boolean).join(' / ')}
        </p>
      )}
      <Heading
        id={headingId}
        className="font-mkt-display text-mkt-d2 text-mkt-ink max-w-[18ch] font-medium"
      >
        {title}
      </Heading>
      {intro && <p className="text-mkt-body text-mkt-ink-soft lg:pt-2">{intro}</p>}
    </Reveal>
  );
}
