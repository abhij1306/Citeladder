import { cva } from 'class-variance-authority';

import { cn } from '@/lib/utils';

/**
 * Card is a flat semantic object, not a structural layout container.
 */
const cardVariants = cva('bg-panel rounded-[var(--radius-card)]');

export type CardTone = 'default' | 'danger';

export const cardClasses = (tone: CardTone = 'default') =>
  cn(cardVariants({}), tone === 'danger' && 'border-danger-border border');
