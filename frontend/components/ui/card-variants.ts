import { cva } from 'class-variance-authority';

/**
 * Card is a flat semantic object, not a structural layout container.
 */
const cardVariants = cva('bg-panel rounded-[var(--radius-card)]');

export const cardClasses = () => cardVariants({});
