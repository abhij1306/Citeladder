import { cva } from 'class-variance-authority';

/**
 * Button CVA — token-driven surfaces (§8). Variants map to semantic bridged
 * tokens only (no raw hex). Sizes use the control-height tokens via bridged
 * `h-*` utilities defined in globals.css (--control-height*).
 *
 * App buttons use the semantic 10px control radius, not pills. Website/auth primary buttons
 * add their inset edge and 12px corners through the scoped `.website-type`
 * contract in globals.css; behaviour and semantics remain shared here.
 * Primary uses the navy action role. Indigo remains analytical selection.
 * Secondary/neutral/ghost stay quiet so a screen has one obvious action.
 *
 * Hover moves the fill one step along the accent ramp rather than fading
 * opacity, so the label keeps its verified AA contrast in every state.
 *
 * Quiet variants walk the semantic alpha-neutral ladder
 * (bg-alt 6% → bg-well 14% → bg-active 31%) instead of swapping between two
 * opaque greys. Because the fills are alpha, `neutral` and `ghost` look
 * correct on a white card, on the sunken canvas, and inside a tinted panel —
 * an opaque grey only ever matched one of the three. `secondary` is the quiet
 * tonal alternate action; public website and auth surfaces opt into their
 * approved outlined treatment at those scoped call sites.
 */
export const buttonVariants = cva(
  'focus-ring inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-control)] border font-sans font-medium no-underline transition-[transform,background-color,color,border-color,box-shadow] duration-[160ms] ease-out active:scale-[0.98] disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-75',
  {
    variants: {
      variant: {
        primary:
          'border-transparent bg-action text-action-fg hover:bg-action-hover active:bg-action-active',
        // Secondary is the quiet tonal alternate action in authenticated flows.
        secondary: 'border-transparent bg-well text-foreground hover:bg-active active:bg-active',
        tonal:
          'border-accent-border bg-accent-subtle text-accent-text hover:border-accent hover:bg-accent-border active:bg-accent-border',
        neutral:
          'border-transparent bg-background-alt text-foreground hover:bg-well active:bg-active',
        ghost:
          'border-transparent bg-transparent text-secondary hover:bg-background-alt hover:text-foreground active:bg-well',
        // Destructive paints on its OWN fill token, not on `--danger`, which is
        // also the sentiment-negative solid and the score-low ring.
        // `--danger-solid` / `-hover` are the shared destructive pair, which
        // clear AA against their foreground —
        // no hand-deepening, unlike the previous system. Hover walks the ramp
        // instead of fading opacity, which used to wash the label out along with
        // the fill. globals.test.ts gates both `danger-fg` ↔ fill pairs.
        destructive:
          'border-transparent bg-danger-solid text-danger-fg hover:bg-danger-solid-hover active:bg-danger-solid-hover',
        destructiveGhost:
          'border-transparent bg-transparent text-danger-text hover:bg-danger-bg active:bg-danger-bg',
      },
      size: {
        sm: 'h-[var(--control-height-sm)] px-2.5 text-sm font-medium',
        md: 'h-[var(--control-height)] px-3.5 text-sm font-medium',
        lg: 'h-[var(--control-height-lg)] px-[var(--card-padding-large)] text-sm font-medium',
        icon: 'size-[var(--control-height)] px-0',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
    },
  },
);
