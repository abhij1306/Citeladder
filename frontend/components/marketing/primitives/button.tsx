import Link from 'next/link';
import type { ComponentPropsWithoutRef, ReactNode } from 'react';

import { cn } from '@/lib/utils';

/**
 * The one button on the Proof surface. Every button is a ROUNDED PILL, and
 * the surface has exactly ONE action colour.
 *
 * That colour is now BLUE, in two intensities: `glass` is the lit pill for the
 * one headline action on a page, `primary` is the flat form of the same blue
 * for every other action. It used to be slate, which was coherent while slate
 * was the only accent — but a blue hero CTA above a slate nav button is the
 * page disagreeing with itself about what an action looks like, and that is
 * the single most visible inconsistency on the surface.
 *
 * The division of labour after the change: BLUE = action, SLATE = brand ink,
 * data marks and the headline sweep, GREEN/RED/AMBER = state. Reverting is one
 * token swap back to `--color-mkt-accent` in the four intents below.
 *
 * Fine pointers get a responsive 2px hover lift; every pointer gets a short
 * press settle so the control stays physically connected to the interaction.
 */
const INTENT = {
  /** Default page action — the flat blue pill. */
  primary: 'bg-mkt-proof text-mkt-surface hover:bg-mkt-proof-hover',
  /** Companion action — quiet blue on the soft blue tint, hairline ring. */
  secondary:
    'bg-mkt-proof-soft text-mkt-proof-hover ring-mkt-proof-line/60 ring-1 ring-inset hover:bg-mkt-surface',
  /** Retained alias so `intent="proof"` call sites keep the one action colour. */
  proof: 'bg-mkt-proof text-mkt-surface hover:bg-mkt-proof-hover',
  /** For use ON the wallpaper, where a white button would disappear. */
  scene: 'bg-mkt-proof text-mkt-surface hover:bg-mkt-proof-hover',
  /**
   * The hero/CTA-beat headline action — the lit blue pill (`.mkt-cta-glass`,
   * marketing-theme.css). Reserved for the ONE action that opens a page or
   * closes it; a second glass button in the same viewport spends the emphasis
   * it exists to buy, which is why this is a named intent and not a size.
   */
  glass: 'mkt-cta-glass',
} as const;

/**
 * The control-height ladder for the whole surface: 40 / 48 / 56, one even
 * 8px step apart. All three sizes carry the same 14px label — they differ in
 * height and padding, not in type size. Shrinking the text too would drop it
 * below the ramp. Rounded-full is the shape decision: actions here are pills.
 *
 * `lg` exists for the glass CTA: a lit pill needs room around the label for
 * the highlight and the arrow disc to read as separate parts rather than a
 * crowded stripe.
 *
 * 56px is off the ADS *spacing* ladder (48/64 are the neighbours) — but a
 * control height is chrome, not spacing, the same documented exception the
 * 72px nav bar takes. What matters is that all three live HERE, so no page
 * can invent a fourth button height.
 */
const SIZE = {
  lg: 'min-h-14 rounded-full pr-3 pl-8 text-mkt-sm',
  md: 'min-h-12 rounded-full px-6 text-mkt-sm',
  sm: 'min-h-10 rounded-full px-4 text-mkt-sm',
} as const;

// The button owns its icon size. Call sites pass `<ArrowRight />` with no
// className — before this, the same arrow in the same component shipped at
// two different sizes depending on the page, because every call site made the
// decision independently. One rung, decided here.
const BASE =
  'inline-flex items-center justify-center gap-3 border border-transparent font-bold ' +
  '[transition:transform_140ms_var(--ease-mkt-out),background-color_200ms_var(--ease-mkt-out),border-color_200ms_var(--ease-mkt-out)] ' +
  'active:[transform:translateY(0)_scale(0.98)] disabled:pointer-events-none disabled:opacity-40 ' +
  '[@media(hover:hover)_and_(pointer:fine)_and_(prefers-reduced-motion:no-preference)]:hover:-translate-y-0.5 ' +
  '[&_svg]:size-4 [&_svg]:shrink-0 ' +
  '[&_svg]:transition-transform [&_svg]:duration-[140ms] [&_svg]:ease-mkt-out ' +
  '[@media(hover:hover)_and_(pointer:fine)_and_(prefers-reduced-motion:no-preference)]:hover:[&_svg]:translate-x-0.5';

type ButtonVisualProps = Readonly<{
  intent?: keyof typeof INTENT;
  size?: keyof typeof SIZE;
  className?: string;
}>;

function classes({ intent = 'primary', size = 'md', className }: ButtonVisualProps) {
  return cn(BASE, INTENT[intent], SIZE[size], className);
}

/** Marketing CTA rendered as a link. Internal hrefs route through next/link. */
export function ButtonLink({
  href,
  intent,
  size,
  className,
  children,
  ...rest
}: ButtonVisualProps & { href: string; children: ReactNode } & Omit<
    ComponentPropsWithoutRef<'a'>,
    'href' | 'className' | 'children'
  >) {
  const props = { className: classes({ intent, size, className }), ...rest };
  // Hash links and mailto/tel must stay plain anchors — next/link would
  // intercept the hash into a route transition and swallow the smooth scroll.
  return href.startsWith('/') ? (
    <Link href={href} {...props}>
      {children}
    </Link>
  ) : (
    <a href={href} {...props}>
      {children}
    </a>
  );
}

/** Marketing action rendered as a real button (menus, toggles, submits). */
export function Button({
  intent,
  size,
  className,
  children,
  type = 'button',
  ...rest
}: ButtonVisualProps & { children: ReactNode } & Omit<
    ComponentPropsWithoutRef<'button'>,
    'className' | 'children'
  >) {
  return (
    <button type={type} className={classes({ intent, size, className })} {...rest}>
      {children}
    </button>
  );
}

/** Underlined text action — the quieter tertiary step. */
export function TextLink({
  href,
  children,
  className,
}: Readonly<{ href: string; children: ReactNode; className?: string }>) {
  const cls = cn(
    'text-mkt-ink border-mkt-line-strong hover:border-mkt-ink inline-flex items-center gap-2',
    'border-b pb-0.5 text-mkt-sm font-bold transition-colors duration-200',
    // Owns its icon size for the same reason the pill does — a call site that
    // forgets falls back to lucide's 24px default next to 14px text.
    '[&_svg]:size-4 [&_svg]:shrink-0',
    className,
  );
  return href.startsWith('/') ? (
    <Link href={href} className={cls}>
      {children}
    </Link>
  ) : (
    <a href={href} className={cls}>
      {children}
    </a>
  );
}
