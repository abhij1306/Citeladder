import { cva } from 'class-variance-authority';

/** Shared visual contract for menus and custom listboxes. */
export const menuPanelClasses =
  'menu-panel border-border-subtle bg-elevated shadow-elevated z-modal overflow-hidden rounded-md border p-1 focus:outline-none';

export const menuItemVariants = cva(
  'text-foreground data-[highlighted]:bg-background-alt data-[active=true]:bg-accent-soft data-[active=true]:text-accent-text data-[state=checked]:bg-accent-soft data-[state=checked]:text-accent-text relative flex min-h-8 cursor-pointer items-center gap-2 rounded-sm py-1 text-sm transition-colors outline-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
  {
    variants: {
      inset: {
        true: 'ps-7 pe-2',
        false: 'px-2',
      },
      selected: {
        true: 'bg-accent-soft text-accent-text',
        false: null,
      },
    },
    defaultVariants: {
      inset: false,
      selected: false,
    },
  },
);
