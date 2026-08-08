import { cva } from 'class-variance-authority';

/**
 * Card — a `bg-panel` fill lifted off the canvas by the shared `shadow-card`
 * rung (docs/design.md: "micro-shadows layered over hairline borders").
 *
 * Elevation is not decoration here: the app canvas is Gray-50 and panels are
 * white, a 2% tonal step that alone reads as one undifferentiated blob once a
 * page stacks several panels. The shadow is what makes a card legible AS a
 * card — so it belongs on the primitive, not opted into per call site.
 *
 * `shadow-card` already carries its own `0 0 0 1px` hairline ring, which is why
 * no `border` utility is applied: a border plus the ring would double the edge.
 * Interactive cards add `hover:shadow-card-hover` (the overlay rung); the
 * transition is retained for them.
 */
export const cardVariants = cva(
  'bg-panel shadow-card rounded-lg transition-[box-shadow,border-color] duration-[330ms] ease-standard',
);

export const cardClasses = () => cardVariants({});
