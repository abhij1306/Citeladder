import { cva } from 'class-variance-authority';

/**
 * Card — a `bg-panel` fill lifted off the canvas by the shared diffuse
 * `shadow-card` rung.
 *
 * Elevation is applied only when the component is genuinely a card. Structural
 * regions can stay on the white canvas or use the neutral highlight without
 * adopting this primitive.
 *
 * The primitive does not impose a border. A surface that needs a stronger edge
 * can add the semantic border utilities at its owning call site. Interactive
 * cards add `hover:shadow-card-hover`; the transition is retained for them.
 */
const cardVariants = cva(
  'bg-panel border border-border shadow-card rounded-[var(--radius-card)] transition-all duration-[180ms] ease-out',
);

export const cardClasses = () => cardVariants({});
