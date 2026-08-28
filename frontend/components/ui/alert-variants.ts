import { cva } from 'class-variance-authority';

/** Compact inline feedback. Tone is carried by icon and text, never a box. */
export const alertVariants = cva('flex items-start gap-2 text-xs', {
  variants: {
    tone: {
      danger: 'text-danger-text',
      warning: 'text-warning-text',
      success: 'text-success-text',
      info: 'text-info-text',
      neutral: 'text-secondary',
    },
  },
  defaultVariants: {
    tone: 'danger',
  },
});
