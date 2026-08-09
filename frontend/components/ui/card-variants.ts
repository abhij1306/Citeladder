import { cva } from 'class-variance-authority';

/**
 * Card — a `bg-panel` fill lifted off the canvas by the shared `shadow-card`
 * rung (docs/design.md: one crisp near edge plus a soft ambient drop).
 *
 * Elevation is applied only when the component is genuinely a card. Structural
 * regions can stay on the white canvas or use the neutral highlight without
 * adopting this primitive.
 *
 * `shadow-card` already carries its own `0 0 0 1px` hairline ring, which is why
 * no `border` utility is applied: a border plus the ring would double the edge.
 * Interactive cards add `hover:shadow-card-hover` (the overlay rung); the
 * transition is retained for them.
 */
export const cardVariants = cva(
  'bg-panel shadow-card rounded-lg transition-shadow duration-[180ms] ease-out',
);

export const cardClasses = () => cardVariants({});
