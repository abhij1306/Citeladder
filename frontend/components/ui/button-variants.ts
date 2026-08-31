import { cva } from 'class-variance-authority';

/**
 * Button CVA — token-driven surfaces (§8). Variants map to semantic bridged
 * tokens only (no raw hex). Sizes use the control-height tokens via bridged
 * `h-*` utilities defined in globals.css (--control-height*).
 *
 * App buttons use the semantic 6px control radius, not pills. Website/auth primary buttons
 * add their inset edge and 12px corners through the scoped `.website-type`
 * contract in globals.css; behaviour and semantics remain shared here.
 * Primary is an accent fill (`bg-accent` + `text-accent-fg`), replacing the
 * flat phase's monochrome `bg-foreground` pill; the accent is no longer
 * reserved away from actions, since the primary action is exactly the thing a
 * dashboard should point at. Secondary/neutral/ghost stay quiet so a screen
 * has one obvious action.
 *
 * Hover moves the fill one step along the accent ramp rather than fading
 * opacity, so the label keeps its verified AA contrast in every state.
 *
 * Flat 2.0: the quiet variants now walk the ADS alpha-neutral ladder
 * (bg-alt 6% → bg-well 14% → bg-active 31%) instead of swapping between two
 * opaque greys. Because the fills are alpha, `neutral` and `ghost` look
 * correct on a white card, on the sunken canvas, and inside a tinted panel —
 * an opaque grey only ever matched one of the three. `secondary` keeps its
 * hairline and panel fill: it is the outline button, and on a sunken canvas
 * that reads as the raised option without needing a shadow.
 */
export const buttonVariants = cva(
  'focus-ring inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-control)] border font-sans font-medium no-underline transition-[transform,background-color,color,border-color,box-shadow] duration-[160ms] ease-out active:scale-[0.98] disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-75',
  {
    variants: {
      variant: {
        primary:
          'border-transparent bg-accent text-accent-fg hover:bg-accent-hover active:bg-accent-active shadow-xs',
        // Secondary is Tesla's white alternate action: a white fill, Graphite
        // label, and a Pale Silver hairline — an outline button, not a raised
        // one, now that elevation is essentially none. Hover warms the fill.
        secondary:
          'border-border-strong bg-panel text-foreground hover:border-border-bold hover:bg-background-alt active:bg-well shadow-xs',
        tonal:
          'border-accent-border bg-accent-subtle text-accent-text hover:border-accent hover:bg-accent-border active:bg-accent-border',
        neutral:
          'border-transparent bg-background-alt text-foreground hover:bg-well active:bg-active',
        ghost:
          'border-transparent bg-transparent text-secondary hover:bg-background-alt hover:text-foreground active:bg-well',
        // Destructive paints on its OWN fill token, not on `--danger`, which is
        // also the sentiment-negative solid and the score-low ring.
        // `--danger-solid` / `-hover` are the ADS background.danger.bold and
        // -bold-hovered pair, which already clear AA against their foreground —
        // no hand-deepening, unlike the previous system. Hover walks the ramp
        // instead of fading opacity, which used to wash the label out along with
        // the fill. globals.test.ts gates both `danger-fg` ↔ fill pairs.
        destructive:
          'border-transparent bg-danger-solid text-danger-fg hover:bg-danger-solid-hover active:bg-danger-solid-hover shadow-xs',
        destructiveGhost:
          'border-transparent bg-transparent text-danger-text hover:bg-danger-bg active:bg-danger-bg',
      },
      size: {
        sm: 'h-[var(--control-height-sm)] px-2.5 text-xs font-medium',
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
